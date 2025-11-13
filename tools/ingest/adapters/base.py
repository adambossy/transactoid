from typing import Protocol, List
from tools.ingest.ingest_tool import NormalizedTransaction

class BankAdapter(Protocol):
    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        ...
