from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import json
import os

from openai import AsyncOpenAI
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
        max_concurrency: int = 8,
    ) -> None:
        self._taxonomy = taxonomy
        self._prompt_key = prompt_key
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._file_cache = file_cache or FileCache()
        self._max_concurrency = max_concurrency
        self._semaphore: asyncio.Semaphore | None = None

    async def categorize(
        self, txns: Iterable[Transaction], *, batch_size: int | None = None
    ) -> list[CategorizedTransaction]:
        txn_list = list(txns)
        if not txn_list:
            return []

        # Initialize semaphore lazily (requires event loop)
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)

        # If no batch size specified, process all transactions in one batch
        if batch_size is None or batch_size >= len(txn_list):
            return await self._categorize_batch(txn_list)

        # Split into batches and process concurrently with semaphore limiting
        batches = [
            txn_list[i : i + batch_size] for i in range(0, len(txn_list), batch_size)
        ]
        print(
            f"Categorizing {len(txn_list)} transactions in {len(batches)} batches "
            f"(max concurrency: {self._max_concurrency})..."
        )

        tasks = [self._categorize_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        # Flatten results
        all_categorized: list[CategorizedTransaction] = []
        for result in batch_results:
            all_categorized.extend(result)

        return all_categorized

    async def _categorize_batch(
        self, txn_list: list[Transaction]
    ) -> list[CategorizedTransaction]:
        """Categorize a single batch of transactions."""
        txn_json_list = self._format_transactions_for_prompt(txn_list)
        taxonomy_dict = self._taxonomy.to_prompt()
        prompt = self._render_prompt(txn_json_list, taxonomy_dict)
        cache_key = self._create_cache_key(txn_json_list, taxonomy_dict)

        cached_result = self._file_cache.get("categorize", cache_key)
        if cached_result is not None:
            return self._parse_response(cached_result, txn_list)

        self._print_api_call_info(txn_list)
        response_text = await self._call_openai_api(prompt)
        self._file_cache.set("categorize", cache_key, response_text)

        return self._parse_response(response_text, txn_list)

    def _print_api_call_info(self, txn_list: list[Transaction]) -> None:
        """Print information about the API call being made."""
        if len(txn_list) == 0:
            return

        first_date = txn_list[0].get("date", "unknown")
        last_date = txn_list[-1].get("date", "unknown")

        if first_date == last_date:
            date_info = f"date: {first_date}"
        else:
            date_info = f"{first_date} to {last_date}"

        print(
            f"Calling OpenAI API for {len(txn_list)} transactions ({date_info})..."
        )

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
        taxonomy_rules = load_prompt("taxonomy-rules")

        rendered = template.replace("{{TAXONOMY_HIERARCHY}}", taxonomy_text)
        rendered = rendered.replace("{{TAXONOMY_RULES}}", taxonomy_rules)
        rendered = rendered.replace("{{CTV_JSON}}", txn_json_str)
        return rendered

    def _create_cache_key(
        self, txn_json_list: list[dict[str, object]], taxonomy_dict: dict[str, object]
    ) -> str:
        """Create deterministic cache key from transactions and taxonomy."""
        taxonomy_rules = load_prompt("taxonomy-rules")
        cache_payload = {
            "txns": txn_json_list,
            "taxonomy": taxonomy_dict,
            "taxonomy_rules": taxonomy_rules,
            "model": self._model,
        }
        return stable_key(cache_payload)

    async def _call_openai_api(self, prompt: str) -> str:
        """Call OpenAI Responses API with web search enabled."""
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")

        # Use semaphore to limit concurrent API calls
        if self._semaphore is None:
            raise RuntimeError("Semaphore not initialized - call categorize() first")
        async with self._semaphore:
            client = AsyncOpenAI(api_key=api_key)
            resp = await client.responses.create(
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
        categorized = self._map_results_to_transactions(response.results, txns)
        self._print_categorization_summary(categorized)
        return categorized

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
        """Determine which category key to use, preferring revised if valid."""
        if result.revised_category and self._taxonomy.is_valid_key(
            result.revised_category
        ):
            return result.revised_category
        if not self._taxonomy.is_valid_key(result.category):
            raise ValueError(
                f"Invalid category key '{result.category}' for transaction "
                f"idx {result.idx}"
            )
        return result.category

    def _validate_revised_category(self, revised_category: str | None) -> str | None:
        """Validate revised category key, returning None if invalid."""
        if revised_category and not self._taxonomy.is_valid_key(revised_category):
            return None
        return revised_category

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
