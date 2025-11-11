from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Literal, Optional, Protocol

Source = Literal["CSV", "PLAID"]


@dataclass
class NormalizedTransaction:
    external_id: Optional[str]
    account_id: str
    posted_at: date
    amount_cents: int
    currency: str
    merchant_descriptor: str
    source: Source
    source_file: Optional[str] = None
    institution: str = ""


class IngestTool(Protocol):
    def fetch_next_batch(self, batch_size: int) -> List[NormalizedTransaction]:
        ...


