from __future__ import annotations

from datetime import date
from pathlib import Path
import csv
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytest


# Skip this whole module if ingest tools don't exist yet.
ingest_tool_mod = pytest.importorskip(
    "tools.ingest.ingest_tool", reason="ingest tools not stubbed/implemented yet"
)

from tools.ingest.csv import CSVIngest
from tools.ingest.plaid import PlaidIngest
from tools.ingest.ingest_tool import NormalizedTransaction


# -----------------------------
# Human-readable expectations
# -----------------------------
# What this suite verifies for tools/ingest/*:
# - CSVIngest:
#   - Recursively scans a directory of CSV files and emits NormalizedTransaction objects.
#   - Sets source="CSV" and source_file=<filename only>.
#   - Infers institution from filename/header heuristics (this suite uses filename prefix as a simple heuristic).
#   - Uses CSV native id when provided; otherwise computes a canonical external_id stable hash.
# - PlaidIngest:
#   - Uses Plaid transaction_id when present; otherwise computes the same canonical external_id hash rule.
#   - Sets source="PLAID" and fills institution from item metadata.
# - Canonical external_id when missing:
#   - sha256 of a stable JSON payload with keys:
#       posted_at (YYYY-MM-DD), amount_cents (int), currency (upper),
#       normalized_merchant_descriptor (lowercased, digits stripped, whitespace collapsed),
#       account_id, institution, source
#   - The digest length must be 64 hex chars.
#
# The tests focus on input → output mapping and keep setup logic in helper functions for readability.


# -----------------------------
# Helper functions
# -----------------------------


def _normalize_descriptor_for_hash(merchant_descriptor: str) -> str:
    lowered = merchant_descriptor.lower().strip()
    no_digits = re.sub(r"\d+", "", lowered)
    collapsed = re.sub(r"\s+", " ", no_digits).strip()
    return collapsed


def canonical_external_id_for(
    *,
    posted_at: date,
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
        "normalized_merchant_descriptor": _normalize_descriptor_for_hash(
            merchant_descriptor
        ),
        "account_id": account_id,
        "institution": institution,
        "source": source,
    }
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(stable).hexdigest()


def build_csv_dir_with(
    tmp_path: Path,
    files: Iterable[Tuple[str, List[Dict[str, Any]]]],
) -> Path:
    """
    Create CSV files with a common header. Each item is (filename, rows).
    Header columns: id,account_id,date,amount,currency,name
    """
    for filename, rows in files:
        fpath = tmp_path / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with fpath.open("w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["id", "account_id", "date", "amount", "currency", "name"]
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return tmp_path


class _FakePlaidClient:
    def __init__(
        self,
        *,
        transactions: List[Dict[str, Any]],
        institution_name: Optional[str] = None,
    ) -> None:
        self._transactions = transactions
        self._institution_name = institution_name or "Chase"

    # Minimal surface the ingest tool might rely on
    def list_transactions(
        self,
        access_token: str,
        *,
        start_date: date,
        end_date: date,
        account_ids: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        return self._transactions[offset : offset + limit]

    def institution_name_for_item(self, access_token: str) -> Optional[str]:
        return self._institution_name


def assert_txn_matches_expected_dict(
    txn: NormalizedTransaction, expected: Dict[str, Any]
) -> None:
    assert txn.external_id == expected["external_id"]
    assert txn.account_id == expected["account_id"]
    assert txn.posted_at == expected["posted_at"]
    assert txn.amount_cents == expected["amount_cents"]
    assert txn.currency == expected["currency"]
    assert txn.merchant_descriptor == expected["merchant_descriptor"]
    assert txn.source == expected["source"]
    assert txn.source_file == expected.get("source_file")
    assert txn.institution == expected["institution"]


def _txn_as_dict(txn: NormalizedTransaction) -> Dict[str, Any]:
    return {
        "external_id": txn.external_id,
        "account_id": txn.account_id,
        "posted_at": txn.posted_at,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "merchant_descriptor": txn.merchant_descriptor,
        "source": txn.source,
        "source_file": txn.source_file,
        "institution": txn.institution,
    }


def create_csv_ingest(
    tmp_path: Path, input_filename: str, input_rows: List[Dict[str, Any]]
) -> CSVIngest:
    build_csv_dir_with(tmp_path, [(input_filename, input_rows)])
    return CSVIngest(data_dir=str(tmp_path))


def create_plaid_ingest(
    input_transactions: List[Dict[str, Any]], institution_name: str
) -> PlaidIngest:
    client = _FakePlaidClient(
        transactions=input_transactions, institution_name=institution_name
    )
    return PlaidIngest(client)


def _fetch_one_as_dict(ingest: Any, batch_size: int) -> Dict[str, Any]:
    output_list = ingest.fetch_next_batch(batch_size)
    assert len(output_list) == 1
    return _txn_as_dict(output_list[0])


# -----------------------------
# CSV ingest cases
# -----------------------------


def test_csv_ingest_maps_basic_fields_and_uses_native_id_when_present(
    tmp_path: Path,
) -> None:
    input_rows = [
        {
            "id": "TXN-001",
            "account_id": "acc-1",
            "date": "2024-01-12",
            "amount": "-12.50",
            "currency": "usd",
            "name": "STARBUCKS 1234",
        }
    ]
    input_filename = "Chase_2024-01.csv"

    # helper setup
    ingest = create_csv_ingest(tmp_path, input_filename, input_rows)

    # function under test
    output = _fetch_one_as_dict(ingest, batch_size=25)

    # expected
    expected_output = {
        "external_id": "TXN-001",
        "account_id": "acc-1",
        "posted_at": date(2024, 1, 12),
        "amount_cents": -1250,
        "currency": "USD",
        "merchant_descriptor": "STARBUCKS 1234",
        "source": "CSV",
        "source_file": input_filename,
        "institution": "Chase",
    }
    assert output == expected_output


def test_csv_ingest_computes_canonical_hash_when_id_missing(tmp_path: Path) -> None:
    input_rows = [
        {
            "id": "",  # missing
            "account_id": "acct-xyz",
            "date": "2024-03-05",
            "amount": "100.00",
            "currency": "USD",
            "name": "WHOLE FOODS 5555",
        }
    ]
    input_filename = "Amex_2024-03.csv"

    # helper setup
    ingest = create_csv_ingest(tmp_path, input_filename, input_rows)

    # function under test
    output = _fetch_one_as_dict(ingest, batch_size=5)

    # expected
    expected_external_id = canonical_external_id_for(
        posted_at=date(2024, 3, 5),
        amount_cents=10000,
        currency="USD",
        merchant_descriptor="WHOLE FOODS 5555",
        account_id="acct-xyz",
        institution="Amex",
        source="CSV",
    )
    expected_output = {
        "external_id": expected_external_id,
        "account_id": "acct-xyz",
        "posted_at": date(2024, 3, 5),
        "amount_cents": 10000,
        "currency": "USD",
        "merchant_descriptor": "WHOLE FOODS 5555",
        "source": "CSV",
        "source_file": input_filename,
        "institution": "Amex",
    }
    assert len(expected_external_id) == 64
    assert output == expected_output


# -----------------------------
# Plaid ingest cases
# -----------------------------


def test_plaid_ingest_uses_plaid_id_and_sets_institution() -> None:
    input_transactions = [
        {
            "transaction_id": "pld-123",
            "account_id": "acct-1",
            "amount": 42.35,
            "iso_currency_code": "usd",
            "date": "2024-02-01",
            "name": "UBER TRIP",
            "merchant_name": "Uber",
            "pending": False,
            "payment_channel": "online",
            "unofficial_currency_code": None,
        }
    ]
    # helper setup
    ingest = create_plaid_ingest(input_transactions, "Chase")

    # function under test
    output = _fetch_one_as_dict(ingest, batch_size=10)

    # expected
    expected_output = {
        "external_id": "pld-123",
        "account_id": "acct-1",
        "posted_at": date(2024, 2, 1),
        "amount_cents": 4235,
        "currency": "USD",
        "merchant_descriptor": "UBER TRIP",
        "source": "PLAID",
        "source_file": None,
        "institution": "Chase",
    }
    assert output == expected_output


def test_plaid_ingest_computes_canonical_hash_when_id_missing() -> None:
    input_transactions = [
        {
            "transaction_id": None,
            "account_id": "acct-99",
            "amount": -17.8,
            "iso_currency_code": "USD",
            "date": "2024-04-20",
            "name": "TARGET #1234",
            "merchant_name": "Target",
            "pending": False,
            "payment_channel": "in_store",
            "unofficial_currency_code": None,
        }
    ]
    # helper setup
    ingest = create_plaid_ingest(input_transactions, "Amex")

    # function under test
    output = _fetch_one_as_dict(ingest, batch_size=10)

    # expected
    expected_external_id = canonical_external_id_for(
        posted_at=date(2024, 4, 20),
        amount_cents=-1780,
        currency="USD",
        merchant_descriptor="TARGET #1234",
        account_id="acct-99",
        institution="Amex",
        source="PLAID",
    )
    expected_output = {
        "external_id": expected_external_id,
        "account_id": "acct-99",
        "posted_at": date(2024, 4, 20),
        "amount_cents": -1780,
        "currency": "USD",
        "merchant_descriptor": "TARGET #1234",
        "source": "PLAID",
        "source_file": None,
        "institution": "Amex",
    }
    assert len(expected_external_id) == 64
    assert output == expected_output
