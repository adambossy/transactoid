from datetime import date
from pathlib import Path
from typing import Any

from tools.ingest.ingest_tool import NormalizedTransaction

from tools.ingest.adapters.amex import AmexAdapter, canonical_external_id_for


def _create_amex_csv_file(tmp_path: Path, content: str) -> str:
    """Creates a dummy AMEX CSV file and returns its path."""
    file_path = tmp_path / "test_amex_simple.csv"
    file_path.write_text(content)
    return str(file_path)


def _normalize_transaction_as_dict(txn: NormalizedTransaction) -> dict[str, Any]:
    """Converts a NormalizedTransaction object to a dict for comparison."""
    return {
        "external_id": txn.external_id,
        "account_id": txn.account_id,
        "posted_at": txn.posted_at,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "merchant_descriptor": txn.merchant_descriptor,
        "source": txn.source,
        "source_file": str(
            Path(txn.source_file).name
        ),  # Normalize to just the filename
        "institution": txn.institution,
    }


def _parse_and_get_first_transaction_dict(
    adapter: AmexAdapter, file_path: str
) -> dict[str, Any]:
    """Parses the file and returns the first transaction as a dict."""
    transactions = adapter.parse(file_path)
    assert len(transactions) == 1, "Expected exactly one transaction"
    return _normalize_transaction_as_dict(transactions[0])


def test_amex_adapter_parses_simple_csv_correctly(tmp_path: Path):
    # Input
    input_csv_content = """Date,Description,Card Member,Account #,Amount
08/29/2025,UBER,JENNY O LEARY,-11016,11.18
"""

    # Helper setup
    file_path = _create_amex_csv_file(tmp_path, input_csv_content)
    adapter = AmexAdapter()

    # Act
    output = _parse_and_get_first_transaction_dict(adapter, file_path)

    # Expected
    posted_at = date(2025, 8, 29)
    amount_cents = 1118
    account_id = "-11016"
    merchant_descriptor = "UBER"

    expected_external_id = canonical_external_id_for(
        posted_at=posted_at,
        amount_cents=amount_cents,
        currency="USD",
        merchant_descriptor=merchant_descriptor,
        account_id=account_id,
        institution="AMEX",
        source="CSV",
    )

    expected_output = {
        "external_id": expected_external_id,
        "account_id": account_id,
        "posted_at": posted_at,
        "amount_cents": amount_cents,
        "currency": "USD",
        "merchant_descriptor": merchant_descriptor,
        "source": "CSV",
        "source_file": "test_amex_simple.csv",
        "institution": "AMEX",
    }

    # Assert
    assert output == expected_output
