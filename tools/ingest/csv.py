from __future__ import annotations

from typing import List

from .ingest_tool import IngestTool, NormalizedTransaction


class CSVIngest(IngestTool):
    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir

    def fetch_next_batch(self, batch_size: int) -> List[NormalizedTransaction]:
        # Minimal stub: no data
        return []
