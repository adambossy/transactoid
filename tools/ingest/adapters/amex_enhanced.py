import csv
from datetime import datetime
from typing import List

from tools.ingest.ingest_tool import NormalizedTransaction
from .base import BankAdapter

class AmexEnhancedAdapter(BankAdapter):
    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        transactions = []
        with open(file_path, 'r') as f:
            reader = csv.reader(f)
            # Skip the first 6 header rows
            for _ in range(6):
                next(reader)

            # Read the header row to get column names
            header = next(reader)

            for row in reader:
                row_data = dict(zip(header, row))

                # Convert amount to cents
                amount_float = float(row_data['Amount'])
                amount_cents = int(amount_float * 100)

                # Parse date
                posted_at = datetime.strptime(row_data['Date'], '%m/%d/%Y').date()

                transactions.append(NormalizedTransaction(
                    external_id=row_data['Reference'],
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
