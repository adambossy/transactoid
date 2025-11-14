from typing import List
from tools.ingest.ingest_tool import NormalizedTransaction
from .base import BankAdapter

class MorganStanleyAdapter(BankAdapter):
    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        raise NotImplementedError
