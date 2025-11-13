from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from tools.ingest.adapters.amex_enhanced import AmexEnhancedAdapter
from tools.ingest.ingest_tool import NormalizedTransaction


def _create_amex_csv_file(tmp_path: Path, content: str) -> str:
    """Creates a dummy AMEX CSV file and returns its path."""
    file_path = tmp_path / "test_amex.csv"
    file_path.write_text(content)
    return str(file_path)


def _normalize_transaction_as_dict(txn: NormalizedTransaction) -> Dict[str, Any]:
    """Converts a NormalizedTransaction object to a dict for comparison."""
    return {
        "external_id": txn.external_id,
        "account_id": txn.account_id,
        "posted_at": txn.posted_at,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "merchant_descriptor": txn.merchant_descriptor,
        "source": txn.source,
        "source_file": str(Path(txn.source_file).name), # Normalize to just the filename
        "institution": txn.institution,
    }


def _parse_and_get_first_transaction_dict(adapter: AmexEnhancedAdapter, file_path: str) -> Dict[str, Any]:
    """Parses the file and returns the first transaction as a dict."""
    transactions = adapter.parse(file_path)
    assert len(transactions) == 1, "Expected exactly one transaction"
    return _normalize_transaction_as_dict(transactions[0])


def test_amex_adapter_parses_csv_correctly(tmp_path: Path):
    # Input
    input_csv_content = """Transaction Details,"American Express Gold Card / Jan 01, 2025 to Aug 30, 2025",,,,,,,,,,,
Prepared for,,,,,,,,,,,,
ADAM BOSSY,,,,,,,,,,,,
Account Number,,,,,,,,,,,,
XXXX-XXXXXX-11008,,,,,,,,,,,,
,,,,,,,,,,,,
Date,Description,Card Member,Account #,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category
08/29/2025,UBER,JENNY O LEARY,-11016,11.18,"EBHM6M1B SF76ERQ6 10014",Uber Trip help.uber.com CA,"1455 MARKET ST","SAN FRANCISCO CA",94103,UNITED STATES,320252410422442649,Transportation-Taxis & Coach
"""

    # Helper setup
    file_path = _create_amex_csv_file(tmp_path, input_csv_content)
    adapter = AmexEnhancedAdapter()

    # Act
    output = _parse_and_get_first_transaction_dict(adapter, file_path)

    # Expected
    expected_output = {
        "external_id": "320252410422442649",
        "account_id": "-11016",
        "posted_at": date(2025, 8, 29),
        "amount_cents": 1118,
        "currency": "USD",
        "merchant_descriptor": "UBER",
        "source": "CSV",
        "source_file": "test_amex.csv",
        "institution": "AMEX",
    }

    # Assert
    assert output == expected_output
