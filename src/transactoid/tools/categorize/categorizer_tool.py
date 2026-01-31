from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets

import loguru
from loguru import logger
from openai import AsyncOpenAI
from promptorium import PromptService, load_prompt
from promptorium.storage import FileSystemPromptStorage
from promptorium.util.repo_root import find_repo_root
from pydantic import BaseModel, Field

from models.transaction import Transaction
from transactoid.adapters.cache.file_cache import FileCache, stable_key
from transactoid.taxonomy.core import Taxonomy
from transactoid.utils.yaml import dump_yaml_basic


@dataclass
class CategorizedTransaction:
    txn: Transaction
    category_key: str
    category_confidence: float
    category_rationale: str
    revised_category_key: str | None = None
    revised_category_confidence: float | None = None
    revised_category_rationale: str | None = None
    merchant_summary: str | None = None


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
    merchant_summary: str | None = Field(
        None,
        description="3-5 bullet points summarizing merchant findings from web search",
    )
    citations: list[str] | None = Field(None, description="Web pages used for revision")


class CategorizationResponse(BaseModel):
    """Response containing multiple categorization results."""

    results: list[CategorizationResult]

    @classmethod
    def parse_json(cls, json_str: str) -> CategorizationResponse:
        """Parse JSON string into CategorizationResponse.

        Handles both formats:
        - Object with "results" key: {"results": [...]}
        - Raw array: [...]
        """
        data = json.loads(json_str)
        if isinstance(data, dict) and "results" in data:
            return cls(
                results=[
                    CategorizationResult.model_validate(item)
                    for item in data["results"]
                ]
            )
        if isinstance(data, list):
            return cls(
                results=[CategorizationResult.model_validate(item) for item in data]
            )
        raise ValueError(
            f"Expected JSON object with 'results' or array, got {type(data)}"
        )


class CategorizerLogger:
    """Handles all logging for the categorizer with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance

    def api_call(self, txn_list: list[Transaction]) -> None:
        """Log API call with formatted transaction context."""
        if not txn_list:
            return

        date_range = self._format_date_range(txn_list)
        self._logger.bind(transaction_count=len(txn_list), date_range=date_range).info(
            "Calling OpenAI API for {} transactions ({})", len(txn_list), date_range
        )

    def batch_start(
        self, total_txns: int, num_batches: int, max_concurrency: int
    ) -> None:
        """Log batch processing start."""
        self._logger.info(
            "Categorizing {} transactions in {} batches (max concurrency: {})",
            total_txns,
            num_batches,
            max_concurrency,
        )

    def categorization_summary(self, categorized: list[CategorizedTransaction]) -> None:
        """Log categorization completion summary."""
        recategorized_count = sum(
            1 for c in categorized if c.revised_category_key is not None
        )
        self._logger.bind(
            total_categorized=len(categorized), recategorized=recategorized_count
        ).info(
            "LLM categorization complete: {} categorized, {} recategorized",
            len(categorized),
            recategorized_count,
        )

    def _format_date_range(self, txn_list: list[Transaction]) -> str:
        """Format transaction date range for display."""
        first_date = txn_list[0].get("date", "unknown")
        last_date = txn_list[-1].get("date", "unknown")

        if first_date == last_date:
            return f"date: {first_date}"
        return f"{first_date} to {last_date}"


class CategorizerAPILogger:
    """Logs OpenAI API calls with inputs and outputs to structured JSON files."""

    def __init__(self, base_dir: str = ".logs/categorizer") -> None:
        self._base_dir = Path(base_dir)

    def create_session(self) -> str:
        """Create a new session directory and return the session ID."""
        session_id = self._generate_session_id()
        session_dir = self._base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_id

    def log_batch(
        self,
        session_id: str,
        batch_idx: int,
        metadata: dict[str, object],
        transaction_pairs: list[dict[str, object]],
    ) -> None:
        """Write a batch log file with metadata and transaction input/output pairs."""
        session_dir = self._base_dir / session_id
        batch_file = session_dir / f"batch-{batch_idx}.json"

        log_data = {
            "metadata": metadata,
            "transactions": transaction_pairs,
        }

        batch_file.write_text(json.dumps(log_data, indent=2, ensure_ascii=False) + "\n")

    def _generate_session_id(self) -> str:
        """Generate unique session ID with timestamp and random suffix."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        random_suffix = secrets.token_hex(4).upper()
        return f"{timestamp}-{random_suffix}"


class Categorizer:
    def __init__(
        self,
        taxonomy: Taxonomy,
        *,
        prompt_key: str = "categorize-transactions",
        model: str = "gpt-5.2",
        file_cache: FileCache | None = None,
        max_concurrency: int = 16,
    ) -> None:
        self._taxonomy = taxonomy
        self._prompt_key = prompt_key
        self._model = model
        self._file_cache = file_cache or FileCache()
        self._max_concurrency = max_concurrency
        self._semaphore: asyncio.Semaphore | None = None
        self._logger = CategorizerLogger()
        self._api_logger = CategorizerAPILogger()

        # Initialize promptorium service for version lookup
        storage = FileSystemPromptStorage(find_repo_root())
        self._prompt_service = PromptService(storage)

        # Initialize OpenAI client once
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")
        self._client = AsyncOpenAI(api_key=api_key)

    async def categorize(
        self, txns: Iterable[Transaction], *, batch_size: int | None = None
    ) -> list[CategorizedTransaction]:
        txn_list = list(txns)
        if not txn_list:
            return []

        # Initialize semaphore lazily (requires event loop)
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)

        # Create logging session
        session_id = self._api_logger.create_session()

        # If no batch size specified, process all transactions in one batch
        if batch_size is None or batch_size >= len(txn_list):
            return await self._categorize_batch(
                txn_list, session_id=session_id, batch_idx=0
            )

        # Split into batches and process concurrently with semaphore limiting
        batches = [
            txn_list[i : i + batch_size] for i in range(0, len(txn_list), batch_size)
        ]
        self._logger.batch_start(len(txn_list), len(batches), self._max_concurrency)

        tasks = [
            self._categorize_batch(batch, session_id=session_id, batch_idx=idx)
            for idx, batch in enumerate(batches)
        ]
        batch_results = await asyncio.gather(*tasks)

        # Flatten results
        all_categorized: list[CategorizedTransaction] = []
        for result in batch_results:
            all_categorized.extend(result)

        return all_categorized

    async def categorize_constrained(
        self,
        txns: Iterable[Transaction],
        allowed_category_keys: list[str],
        *,
        batch_size: int | None = None,
    ) -> list[CategorizedTransaction]:
        """
        Categorize transactions with limited category options.

        Used by split operations to recategorize among specific targets.
        Creates a filtered taxonomy with only the allowed categories and
        uses it for categorization.

        Args:
            txns: Transactions to categorize
            allowed_category_keys: List of category keys to allow as options
            batch_size: Optional batch size for processing

        Returns:
            List of CategorizedTransaction with categories from allowed set
        """
        txn_list = list(txns)
        if not txn_list:
            return []

        # Validate that all allowed keys exist in taxonomy
        for key in allowed_category_keys:
            if not self._taxonomy.is_valid_key(key):
                msg = f"Category key '{key}' is not valid in taxonomy"
                raise ValueError(msg)

        # Initialize semaphore lazily (requires event loop)
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)

        # Create logging session
        session_id = self._api_logger.create_session()

        # If no batch size specified, process all transactions in one batch
        if batch_size is None or batch_size >= len(txn_list):
            return await self._categorize_batch_constrained(
                txn_list,
                allowed_category_keys,
                session_id=session_id,
                batch_idx=0,
            )

        # Split into batches and process concurrently with semaphore limiting
        batches = [
            txn_list[i : i + batch_size] for i in range(0, len(txn_list), batch_size)
        ]
        self._logger.batch_start(len(txn_list), len(batches), self._max_concurrency)

        tasks = [
            self._categorize_batch_constrained(
                batch,
                allowed_category_keys,
                session_id=session_id,
                batch_idx=idx,
            )
            for idx, batch in enumerate(batches)
        ]
        batch_results = await asyncio.gather(*tasks)

        # Flatten results
        all_categorized: list[CategorizedTransaction] = []
        for result in batch_results:
            all_categorized.extend(result)

        return all_categorized

    async def _categorize_batch_constrained(
        self,
        txn_list: list[Transaction],
        allowed_category_keys: list[str],
        session_id: str,
        batch_idx: int,
    ) -> list[CategorizedTransaction]:
        """Categorize a batch with constrained taxonomy."""
        txn_json_list = self._format_transactions_for_prompt(txn_list)
        # Use filtered taxonomy with only allowed keys
        taxonomy_dict = self._taxonomy.to_prompt(include_keys=allowed_category_keys)
        valid_keys = self._extract_valid_keys(taxonomy_dict)
        prompt = self._render_prompt(txn_json_list, taxonomy_dict)
        cache_key = self._create_cache_key(txn_json_list, taxonomy_dict)

        cached_result = self._file_cache.get("categorize", cache_key)
        if cached_result is not None:
            categorized = self._parse_response(cached_result, txn_list)
            self._log_api_call(
                session_id, batch_idx, txn_json_list, categorized, from_cache=True
            )
            return categorized

        self._logger.api_call(txn_list)
        response_text = await self._call_openai_api(prompt, valid_keys=valid_keys)
        self._file_cache.set("categorize", cache_key, response_text)

        categorized = self._parse_response(response_text, txn_list)
        self._log_api_call(
            session_id, batch_idx, txn_json_list, categorized, from_cache=False
        )
        return categorized

    async def _categorize_batch(
        self, txn_list: list[Transaction], session_id: str, batch_idx: int
    ) -> list[CategorizedTransaction]:
        """Categorize a single batch of transactions."""
        txn_json_list = self._format_transactions_for_prompt(txn_list)
        taxonomy_dict = self._taxonomy.to_prompt()
        valid_keys = self._extract_valid_keys(taxonomy_dict)
        prompt = self._render_prompt(txn_json_list, taxonomy_dict)
        cache_key = self._create_cache_key(txn_json_list, taxonomy_dict)

        cached_result = self._file_cache.get("categorize", cache_key)
        if cached_result is not None:
            categorized = self._parse_response(cached_result, txn_list)
            self._log_api_call(
                session_id, batch_idx, txn_json_list, categorized, from_cache=True
            )
            return categorized

        self._logger.api_call(txn_list)
        response_text = await self._call_openai_api(prompt, valid_keys=valid_keys)
        self._file_cache.set("categorize", cache_key, response_text)

        categorized = self._parse_response(response_text, txn_list)
        self._log_api_call(
            session_id, batch_idx, txn_json_list, categorized, from_cache=False
        )
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

    def _extract_valid_keys(self, taxonomy_dict: dict[str, object]) -> list[str]:
        nodes = taxonomy_dict.get("nodes", [])
        if not isinstance(nodes, list):
            return []
        keys: list[str] = []
        for node in nodes:
            if isinstance(node, dict) and "key" in node:
                keys.append(str(node["key"]))
        return sorted(keys)

    def _build_response_schema(self, valid_keys: list[str]) -> dict[str, object]:
        """Build JSON schema for OpenAI Responses API text.format parameter.

        OpenAI requires top-level type to be "object", so we wrap the array
        in an object with a "results" property.
        """
        return {
            "type": "json_schema",
            "name": "categorization",
            "schema": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "idx": {"type": "integer"},
                                "category": {"type": "string", "enum": valid_keys},
                                "score": {"type": "number"},
                                "rationale": {"type": "string"},
                                "revised_category": {
                                    "anyOf": [
                                        {"type": "null"},
                                        {"type": "string", "enum": valid_keys},
                                    ]
                                },
                                "revised_score": {"type": ["number", "null"]},
                                "revised_rationale": {"type": ["string", "null"]},
                                "merchant_summary": {"type": ["string", "null"]},
                                "citations": {
                                    "anyOf": [
                                        {"type": "null"},
                                        {"type": "array", "items": {"type": "string"}},
                                    ]
                                },
                            },
                            "required": [
                                "idx",
                                "category",
                                "score",
                                "rationale",
                                "revised_category",
                                "revised_score",
                                "revised_rationale",
                                "merchant_summary",
                                "citations",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["results"],
                "additionalProperties": False,
            },
            "strict": True,
        }

    async def _call_openai_api(
        self, prompt: str, *, valid_keys: list[str] | None = None
    ) -> str:
        """Call OpenAI Responses API with web search enabled."""
        # Use semaphore to limit concurrent API calls
        if self._semaphore is None:
            raise RuntimeError("Semaphore not initialized - call categorize() first")
        async with self._semaphore:
            extra_body: dict[str, object] | None = None
            if valid_keys:
                # Responses API uses text.format instead of response_format
                response_schema = self._build_response_schema(valid_keys)
                extra_body = {"text": {"format": response_schema}}
            resp = await self._client.responses.create(
                model=self._model,
                input=prompt,
                tools=[{"type": "web_search"}],
                extra_body=extra_body,
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
        self._logger.categorization_summary(categorized)
        return categorized

    def _extract_json_from_response(self, response_text: str) -> str:
        """Extract JSON from response text.

        Handles both object {"results": [...]} and array [...] formats.
        """
        # Try object format first (preferred)
        obj_start = response_text.find("{")
        obj_end = response_text.rfind("}") + 1
        if obj_start != -1 and obj_end > 0:
            return response_text[obj_start:obj_end]

        # Fall back to array format
        arr_start = response_text.find("[")
        arr_end = response_text.rfind("]") + 1
        if arr_start != -1 and arr_end > 0:
            return response_text[arr_start:arr_end]

        raise ValueError(f"Could not find JSON in response: {response_text[:200]}")

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
            merchant_summary=result.merchant_summary,
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

    def _get_prompt_version(self, key: str) -> int:
        """Get the latest version number for a prompt key."""
        prompts = self._prompt_service.list_prompts()
        for p in prompts:
            if p.ref.key == key:
                return max(v.version for v in p.versions)
        raise ValueError(f"Prompt key '{key}' not found")

    def _log_api_call(
        self,
        session_id: str,
        batch_idx: int,
        txn_json_list: list[dict[str, object]],
        categorized: list[CategorizedTransaction],
        from_cache: bool,
    ) -> None:
        """Log API call inputs and outputs to JSON file."""
        # Get prompt versions
        prompt_version = self._get_prompt_version(self._prompt_key)
        taxonomy_rules_version = self._get_prompt_version("taxonomy-rules")

        metadata = {
            "prompt_key": f"{self._prompt_key}-{prompt_version}",
            "taxonomy_rules_key": f"taxonomy-rules-{taxonomy_rules_version}",
            "model": self._model,
            "timestamp": datetime.now(UTC).isoformat(),
            "batch_idx": batch_idx,
            "session_id": session_id,
            "transaction_count": len(txn_json_list),
            "from_cache": from_cache,
        }

        # Build transaction pairs by matching idx
        transaction_pairs: list[dict[str, object]] = []
        for cat_txn in categorized:
            # Find corresponding input by idx
            input_txn = next(
                (t for t in txn_json_list if t["idx"] == cat_txn.txn.get("idx")),
                None,
            )
            if input_txn is None:
                continue

            output = {
                "idx": input_txn["idx"],
                "category": cat_txn.category_key,
                "score": cat_txn.category_confidence,
                "rationale": cat_txn.category_rationale,
                "revised_category": cat_txn.revised_category_key,
                "revised_score": cat_txn.revised_category_confidence,
                "revised_rationale": cat_txn.revised_category_rationale,
                "merchant_summary": cat_txn.merchant_summary,
            }

            transaction_pairs.append({"input": input_txn, "output": output})

        self._api_logger.log_batch(session_id, batch_idx, metadata, transaction_pairs)
