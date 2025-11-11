from __future__ import annotations

from datetime import date
from typing import List, Optional

from .ingest_tool import IngestTool, NormalizedTransaction


class PlaidIngest(IngestTool):
    def __init__(
        self,
        plaid_client: "PlaidClient",
        *,
        account_ids: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> None:
        self._plaid_client = plaid_client
        self._account_ids = account_ids
        self._start_date = start_date
        self._end_date = end_date

    def fetch_next_batch(self, batch_size: int) -> List[NormalizedTransaction]:
        # Minimal stub: no data
        return []


