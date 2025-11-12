from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from tools.ingest.ingest_tool import NormalizedTransaction


@dataclass
class CategorizedTransaction:
    txn: NormalizedTransaction
    category_key: str
    category_confidence: float
    category_rationale: str
    revised_category_key: Optional[str] = None
    revised_category_confidence: Optional[float] = None
    revised_category_rationale: Optional[str] = None


class Categorizer:
    def __init__(
        self,
        taxonomy: "Taxonomy",
        *,
        prompt_key: str = "categorize-transacations",
        model: str = "gpt-5",
        confidence_threshold: float = 0.70,
    ) -> None:
        self._taxonomy = taxonomy
        self._prompt_key = prompt_key
        self._model = model
        self._confidence_threshold = confidence_threshold

    def categorize(
        self, txns: Iterable[NormalizedTransaction]
    ) -> List[CategorizedTransaction]:
        # Minimal stub: returns empty list
        return []
