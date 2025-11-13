import csv
import hashlib
import json
import re
from datetime import datetime
from typing import List

from tools.ingest.ingest_tool import NormalizedTransaction
from .base import BankAdapter

def _normalize_descriptor_for_hash(merchant_descriptor: str) -> str:
    lowered = merchant_descriptor.lower().strip()
    no_digits = re.sub(r"\d+", "", lowered)
    collapsed = re.sub(r"\s+", " ", no_digits).strip()
    return collapsed


def canonical_external_id_for(
    *,
    posted_at: datetime.date,
    amount_cents: int,
    currency: str,
    merchant_descriptor: str,
    account_id: str,
    institution: str,
    source: str,
) -> str:
    payload = {
        "posted_at": posted_at.isoformat(),
        "amount_cents": int(amount_cents),
        "currency": currency.upper(),
        "normalized_merchant_descriptor": _normalize_descriptor_for_hash(merchant_descriptor),
        "account_id": account_id,
        "institution": institution,
        "source": source,
    }
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(stable).hexdigest()


class AmexAdapter(BankAdapter):
    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        transactions = []
        with open(file_path, 'r') as f:
            reader = csv.reader(f)

            # Read the header row to get column names
            header = next(reader)

            for row in reader:
                row_data = dict(zip(header, row))

                # Convert amount to cents
                amount_float = float(row_data['Amount'])
                amount_cents = int(amount_float * 100)

                # Parse date
                posted_at = datetime.strptime(row_data['Date'], '%m/%d/%Y').date()

                # Generate external_id
                external_id = canonical_external_id_for(
                    posted_at=posted_at,
                    amount_cents=amount_cents,
                    currency='USD',
                    merchant_descriptor=row_data['Description'],
                    account_id=row_data['Account #'].strip(),
                    institution='AMEX',
                    source='CSV'
                )

                transactions.append(NormalizedTransaction(
                    external_id=external_id,
                    account_id=row_data['Account #'].strip(),
                    posted_at=posted_at,
                    amount_cents=amount_cents,
                    currency='USD',
                    merchant_descriptor=row_data['Description'],
                    source='CSV',
                    source_file=file_path,
                    institution='AMEX'
                ))
        return transactions
