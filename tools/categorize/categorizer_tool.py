from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import os

from openai import OpenAI
from promptorium import load_prompt
from pydantic import BaseModel, Field

from models.transaction import Transaction
from services.file_cache import FileCache, stable_key
from services.taxonomy import Taxonomy
from services.yaml_utils import dump_yaml_basic


@dataclass
class CategorizedTransaction:
    txn: Transaction
    category_key: str
    category_confidence: float
    category_rationale: str
    revised_category_key: str | None = None
    revised_category_confidence: float | None = None
    revised_category_rationale: str | None = None


class CategorizationResult(BaseModel):
    """Single categorization result from the LLM."""

    idx: int = Field(..., description="Index matching the input transaction")
    category: str = Field(..., description="Initial category key")
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Initial confidence before search"
    )
    rationale: str = Field(..., description="Initial rationale")
    revised_category: str | None = Field(None, description="Category after web search")
    revised_score: float | None = Field(
        None, ge=0.0, le=1.0, description="Confidence after web search"
    )
    revised_rationale: str | None = Field(
        None, description="Rationale after web search"
    )
    citations: list[str] | None = Field(None, description="Web pages used for revision")


class CategorizationResponse(BaseModel):
    """Response containing multiple categorization results."""

    results: list[CategorizationResult]

    @classmethod
    def parse_json(cls, json_str: str) -> CategorizationResponse:
        """Parse JSON string into CategorizationResponse."""
        data = json.loads(json_str)
        if isinstance(data, list):
            return cls(
                results=[CategorizationResult.model_validate(item) for item in data]
            )
        raise ValueError(f"Expected JSON array, got {type(data)}")


class Categorizer:
    def __init__(
        self,
        taxonomy: Taxonomy,
        *,
        prompt_key: str = "categorize-transactions",
        model: str = "gpt-5.1",
        confidence_threshold: float = 0.70,
        file_cache: FileCache | None = None,
    ) -> None:
        self._taxonomy = taxonomy
        self._prompt_key = prompt_key
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._file_cache = file_cache or FileCache()

    def categorize(self, txns: Iterable[Transaction]) -> list[CategorizedTransaction]:
        txn_list = list(txns)
        if not txn_list:
            return []

        txn_json_list = self._format_transactions_for_prompt(txn_list)
        taxonomy_dict = self._taxonomy.to_prompt()
        prompt = self._render_prompt(txn_json_list, taxonomy_dict)
        cache_key = self._create_cache_key(txn_json_list, taxonomy_dict)

        cached_result = self._file_cache.get("categorize", cache_key)
        if cached_result is not None:
            categorized = self._parse_response(cached_result, txn_list)
        else:
            print(f"Categorizing {len(txn_list)} transactions with LLM...")
            response_text = self._call_openai_api(prompt)
            self._file_cache.set("categorize", cache_key, response_text)
            categorized = self._parse_response(response_text, txn_list)

        # Validate and fix invalid categories with reflexion
        categorized = self._validate_and_fix_categories(categorized, txn_list)

        self._print_categorization_summary(categorized)
        return categorized

    def _format_transactions_for_prompt(
        self, txns: list[Transaction]
    ) -> list[dict[str, object]]:
        """Format transactions with idx for prompt alignment."""
        txn_json_list = []
        for idx, txn in enumerate(txns):
            txn_json_list.append(
                {
                    "idx": idx,
                    "description": txn.get("name", ""),
                    "merchant": txn.get("merchant_name"),
                    "amount": txn.get("amount"),
                    "date": txn.get("date"),
                    "account_id": txn.get("account_id"),
                }
            )
        return txn_json_list

    def _serialize_taxonomy(self, taxonomy_dict: dict[str, object]) -> str:
        """Serialize taxonomy dictionary to YAML string."""
        return dump_yaml_basic(taxonomy_dict, default_flow_style=False, sort_keys=False)

    def _render_prompt(
        self, txn_json_list: list[dict[str, object]], taxonomy_dict: dict[str, object]
    ) -> str:
        """Load prompt template and render with taxonomy and transaction data."""
        template = load_prompt(self._prompt_key)
        taxonomy_text = self._serialize_taxonomy(taxonomy_dict)
        txn_json_str = json.dumps(txn_json_list, ensure_ascii=False, indent=2)
        return template.replace("{{TAXONOMY_HIERARCHY}}", taxonomy_text).replace(
            "{{CTV_JSON}}", txn_json_str
        )

    def _create_cache_key(
        self, txn_json_list: list[dict[str, object]], taxonomy_dict: dict[str, object]
    ) -> str:
        """Create deterministic cache key from transactions and taxonomy."""
        cache_payload = {
            "txns": txn_json_list,
            "taxonomy": taxonomy_dict,
            "model": self._model,
        }
        return stable_key(cache_payload)

    def _call_openai_api(self, prompt: str) -> str:
        """Call OpenAI Responses API with web search enabled."""
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")

        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=self._model,
            input=prompt,
            tools=[{"type": "web_search"}],
        )
        return self._extract_response_text(resp)

    def _extract_response_text(self, resp: object) -> str:
        """Extract text from OpenAI response object."""
        response_text: str | None = getattr(resp, "output_text", None)
        if response_text is None:
            response_text = str(resp)
        return response_text

    def _parse_response(
        self, response_text: str, txns: list[Transaction]
    ) -> list[CategorizedTransaction]:
        """Parse LLM response and map back to transactions."""
        json_str = self._extract_json_from_response(response_text)
        response = self._parse_categorization_response(json_str)
        return self._map_results_to_transactions(response.results, txns)

    def _extract_json_from_response(self, response_text: str) -> str:
        """Extract JSON array from response text."""
        json_start = response_text.find("[")
        json_end = response_text.rfind("]") + 1
        if json_start == -1 or json_end == 0:
            raise ValueError(
                f"Could not find JSON array in response: {response_text[:200]}"
            )
        return response_text[json_start:json_end]

    def _parse_categorization_response(self, json_str: str) -> CategorizationResponse:
        """Parse JSON string into CategorizationResponse using Pydantic."""
        try:
            return CategorizationResponse.parse_json(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e

    def _map_results_to_transactions(
        self, results: list[CategorizationResult], txns: list[Transaction]
    ) -> list[CategorizedTransaction]:
        """Map categorization results back to transactions by idx."""
        categorized: list[CategorizedTransaction] = []
        for result in results:
            if result.idx >= len(txns):
                continue
            categorized.append(self._build_categorized_transaction(result, txns))
        return categorized

    def _build_categorized_transaction(
        self, result: CategorizationResult, txns: list[Transaction]
    ) -> CategorizedTransaction:
        """Build CategorizedTransaction from result and validate category keys."""
        category_key = self._resolve_category_key(result)
        revised_category = self._validate_revised_category(result.revised_category)
        return CategorizedTransaction(
            txn=txns[result.idx],
            category_key=category_key,
            category_confidence=result.score,
            category_rationale=result.rationale,
            revised_category_key=revised_category,
            revised_category_confidence=result.revised_score,
            revised_category_rationale=result.revised_rationale,
        )

    def _resolve_category_key(self, result: CategorizationResult) -> str:
        """Determine which category key to use, preferring revised if valid.

        Note: This method no longer raises on invalid categories. Invalid categories
        are now caught and fixed by the reflexion loop in _validate_and_fix_categories.
        """
        if result.revised_category and self._taxonomy.is_valid_key(
            result.revised_category
        ):
            return result.revised_category
        # Return category even if invalid - will be caught by validation
        return result.category

    def _validate_revised_category(self, revised_category: str | None) -> str | None:
        """Validate revised category key, returning None if invalid."""
        if revised_category and not self._taxonomy.is_valid_key(revised_category):
            return None
        return revised_category

    def _validate_and_fix_categories(
        self,
        categorized: list[CategorizedTransaction],
        txns: list[Transaction],
        max_retries: int = 3,
    ) -> list[CategorizedTransaction]:
        """Validate category keys and fix invalid ones using reflexion.

        Args:
            categorized: Initial categorization results
            txns: Original transaction list
            max_retries: Maximum reflexion attempts (default: 3)

        Returns:
            List of categorized transactions with all valid category keys

        Raises:
            ValueError: If invalid categories remain after max_retries
        """
        attempt = 0
        while attempt < max_retries:
            invalid_indices = self._find_invalid_category_indices(categorized)
            if not invalid_indices:
                return categorized  # All valid, done!

            print(
                f"Found {len(invalid_indices)} invalid categories, "
                f"attempting reflexion fix (attempt {attempt + 1}/{max_retries})..."
            )

            # Fix invalid categories using reflexion
            fixed_results = self._reflexion_fix_invalid_categories(
                categorized, txns, invalid_indices, attempt + 1
            )

            # Update categorized list with fixed results
            for idx, fixed in zip(invalid_indices, fixed_results):
                categorized[idx] = fixed

            attempt += 1

        # Check if any invalid remain after max retries
        remaining_invalid = self._find_invalid_category_indices(categorized)
        if remaining_invalid:
            invalid_keys = [
                categorized[i].category_key for i in remaining_invalid
            ]
            raise ValueError(
                f"Failed to categorize transactions after {max_retries} "
                f"reflexion attempts. Still invalid at indices {remaining_invalid}: "
                f"{invalid_keys}"
            )

        return categorized

    def _find_invalid_category_indices(
        self, categorized: list[CategorizedTransaction]
    ) -> list[int]:
        """Find indices of transactions with invalid category keys.

        Args:
            categorized: List of categorized transactions

        Returns:
            List of indices where category_key is invalid
        """
        invalid_indices: list[int] = []
        for i, cat_txn in enumerate(categorized):
            if not self._taxonomy.is_valid_key(cat_txn.category_key):
                invalid_indices.append(i)
        return invalid_indices

    def _reflexion_fix_invalid_categories(
        self,
        categorized: list[CategorizedTransaction],
        txns: list[Transaction],
        invalid_indices: list[int],
        attempt: int,
    ) -> list[CategorizedTransaction]:
        """Use reflexion to fix invalid category keys.

        Args:
            categorized: Current categorization results
            txns: Original transaction list
            invalid_indices: Indices of transactions with invalid categories
            attempt: Current attempt number (for cache key)

        Returns:
            List of fixed CategorizedTransaction objects in same order as
            invalid_indices
        """
        fixed: list[CategorizedTransaction] = []

        for idx in invalid_indices:
            cat_txn = categorized[idx]
            txn = txns[idx]

            # Build reflexion prompt
            prompt = self._render_reflexion_prompt(
                idx, cat_txn.category_key, txn
            )

            # Check cache first
            cache_key = self._create_reflexion_cache_key(
                cat_txn.category_key, txn, attempt
            )
            cached_result = self._file_cache.get("categorize-reflexion", cache_key)

            if cached_result is not None:
                response_text = cached_result
            else:
                response_text = self._call_openai_api(prompt)
                self._file_cache.set("categorize-reflexion", cache_key, response_text)

            # Parse reflexion response
            try:
                fixed_cat_txn = self._parse_reflexion_response(response_text, txn, idx)
                fixed.append(fixed_cat_txn)
            except (ValueError, json.JSONDecodeError) as e:
                # If reflexion fails, keep original (will retry or fail later)
                print(f"Warning: Reflexion parse failed for idx {idx}: {e}")
                fixed.append(cat_txn)

        return fixed

    def _render_reflexion_prompt(
        self, idx: int, invalid_category: str, txn: Transaction
    ) -> str:
        """Render reflexion prompt for fixing invalid category.

        Args:
            idx: Transaction index
            invalid_category: The invalid category key that was provided
            txn: Transaction data

        Returns:
            Rendered prompt string
        """
        template = load_prompt("reflexion-fix-invalid")

        # Format transaction for prompt
        txn_json = json.dumps(
            {
                "idx": idx,
                "description": txn.get("name", ""),
                "merchant": txn.get("merchant_name"),
                "amount": txn.get("amount"),
                "date": txn.get("date"),
            },
            ensure_ascii=False,
            indent=2,
        )

        # Get valid categories list
        taxonomy_dict = self._taxonomy.to_prompt()
        valid_categories_list = self._format_valid_categories_list(taxonomy_dict)

        # Replace template variables
        return (
            template.replace("{{IDX}}", str(idx))
            .replace("{{INVALID_CATEGORY}}", invalid_category)
            .replace("{{TRANSACTION_JSON}}", txn_json)
            .replace("{{VALID_CATEGORIES_LIST}}", valid_categories_list)
        )

    def _format_valid_categories_list(self, taxonomy_dict: dict[str, object]) -> str:
        """Format taxonomy as a readable list of valid category keys.

        Args:
            taxonomy_dict: Taxonomy dictionary from to_prompt()

        Returns:
            Formatted string listing all valid category keys
        """
        # Extract all category keys from taxonomy
        categories = taxonomy_dict.get("categories", [])
        if isinstance(categories, list):
            keys = [
                cat["key"]
                for cat in categories
                if isinstance(cat, dict) and "key" in cat
            ]
            return "\n".join(f"- {key}" for key in sorted(keys))
        return ""

    def _create_reflexion_cache_key(
        self, invalid_category: str, txn: Transaction, attempt: int
    ) -> str:
        """Create cache key for reflexion attempt.

        Args:
            invalid_category: The invalid category that needs fixing
            txn: Transaction data
            attempt: Attempt number

        Returns:
            Deterministic cache key
        """
        cache_payload = {
            "invalid_category": invalid_category,
            "txn": {
                "name": txn.get("name"),
                "merchant_name": txn.get("merchant_name"),
                "amount": txn.get("amount"),
                "date": txn.get("date"),
            },
            "attempt": attempt,
            "model": self._model,
        }
        return stable_key(cache_payload)

    def _parse_reflexion_response(
        self, response_text: str, txn: Transaction, expected_idx: int
    ) -> CategorizedTransaction:
        """Parse reflexion response into CategorizedTransaction.

        Args:
            response_text: LLM response text
            txn: Original transaction
            expected_idx: Expected index value

        Returns:
            CategorizedTransaction with validated category

        Raises:
            ValueError: If response is invalid or category is still invalid
        """
        # Extract JSON object (not array)
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            raise ValueError(
                f"Could not find JSON object in reflexion response: "
                f"{response_text[:200]}"
            )

        json_str = response_text[json_start:json_end]
        result_dict = json.loads(json_str)

        # Validate structure
        if result_dict.get("idx") != expected_idx:
            raise ValueError(
                f"Reflexion response idx {result_dict.get('idx')} "
                f"does not match expected {expected_idx}"
            )

        category = result_dict.get("category", "")
        if not self._taxonomy.is_valid_key(category):
            raise ValueError(
                f"Reflexion still produced invalid category: {category}"
            )

        # Build CategorizedTransaction
        return CategorizedTransaction(
            txn=txn,
            category_key=category,
            category_confidence=result_dict.get("score", 0.0),
            category_rationale=result_dict.get("rationale", ""),
        )

    def _print_categorization_summary(
        self, categorized: list[CategorizedTransaction]
    ) -> None:
        """Print summary of categorization results."""
        recategorized_count = sum(
            1 for c in categorized if c.revised_category_key is not None
        )
        print(
            f"LLM categorization complete: {len(categorized)} categorized, "
            f"{recategorized_count} recategorized"
        )
