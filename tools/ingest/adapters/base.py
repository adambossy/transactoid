from typing import Protocol

from tools.ingest.ingest_tool import NormalizedTransaction


class BankAdapter(Protocol):
    def parse(self, file_path: str) -> list[NormalizedTransaction]: ...
