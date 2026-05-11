"""Tests for DB.min_plaid_transaction_date facade method."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.db.facade import DB


def create_test_db(tmp_path: Path) -> DB:
    """Create a test database with schema."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


def test_min_plaid_transaction_date_returns_none_for_empty_table(
    tmp_path: Path,
) -> None:
    # input
    db = create_test_db(tmp_path)

    # act
    output = db.min_plaid_transaction_date()

    # expected
    expected_output = None

    # assert
    assert output == expected_output


def test_min_plaid_transaction_date_returns_earliest(tmp_path: Path) -> None:
    # input
    db = create_test_db(tmp_path)
    db.upsert_plaid_transaction(
        external_id="ext-1",
        source="PLAID",
        account_id="acct-1",
        posted_at=date(2024, 6, 15),
        amount_cents=1000,
        currency="USD",
        merchant_descriptor="Merchant 1",
        institution="Bank",
    )
    db.upsert_plaid_transaction(
        external_id="ext-2",
        source="PLAID",
        account_id="acct-1",
        posted_at=date(2023, 1, 5),
        amount_cents=2000,
        currency="USD",
        merchant_descriptor="Merchant 2",
        institution="Bank",
    )
    db.upsert_plaid_transaction(
        external_id="ext-3",
        source="PLAID",
        account_id="acct-1",
        posted_at=date(2025, 12, 20),
        amount_cents=3000,
        currency="USD",
        merchant_descriptor="Merchant 3",
        institution="Bank",
    )

    # act
    output = db.min_plaid_transaction_date()

    # expected
    expected_output = date(2023, 1, 5)

    # assert
    assert output == expected_output
