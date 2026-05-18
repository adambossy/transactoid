"""Tests for facade helpers backing the Amazon remutation flow."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.db.facade import DB


def create_test_db(tmp_path: Path) -> DB:
    """Create an isolated SQLite test database with schema."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


def _add_order(db: DB, *, order_id: str, order_date: date) -> None:
    """Persist one Amazon order under a default profile."""
    profile = db.create_amazon_login_profile(
        profile_key=order_id, display_name=order_id
    )
    db.upsert_amazon_order(
        order_id=order_id,
        order_date=order_date,
        order_total_cents=1000,
        profile_id=profile.profile_id,
    )


def _add_plaid(db: DB, *, external_id: str, posted_at: date) -> None:
    """Persist one Plaid transaction."""
    db.upsert_plaid_transaction(
        external_id=external_id,
        source="PLAID",
        account_id="acct-1",
        posted_at=posted_at,
        amount_cents=1000,
        currency="USD",
        merchant_descriptor="AMAZON.COM",
        institution="Bank",
    )


def test_amazon_order_date_bounds_returns_none_when_empty(tmp_path: Path) -> None:
    # input
    db = create_test_db(tmp_path)

    # act
    output = db.amazon_order_date_bounds()

    # expected
    expected_output = None

    # assert
    assert output == expected_output


def test_amazon_order_date_bounds_returns_min_and_max(tmp_path: Path) -> None:
    # input
    db = create_test_db(tmp_path)
    _add_order(db, order_id="o-early", order_date=date(2024, 2, 6))
    _add_order(db, order_id="o-mid", order_date=date(2025, 7, 1))
    _add_order(db, order_id="o-late", order_date=date(2026, 4, 12))

    # act
    output = db.amazon_order_date_bounds()

    # expected
    expected_output = (date(2024, 2, 6), date(2026, 4, 12))

    # assert
    assert output == expected_output


def test_list_plaid_transactions_in_date_range_filters_and_orders(
    tmp_path: Path,
) -> None:
    # input
    db = create_test_db(tmp_path)
    _add_plaid(db, external_id="before", posted_at=date(2025, 12, 31))
    _add_plaid(db, external_id="in-2", posted_at=date(2026, 3, 1))
    _add_plaid(db, external_id="in-1", posted_at=date(2026, 1, 10))
    _add_plaid(db, external_id="after", posted_at=date(2026, 6, 1))

    # act
    txns = db.list_plaid_transactions_in_date_range(
        start=date(2026, 1, 1), end=date(2026, 5, 1)
    )
    output = [t.external_id for t in txns]

    # expected — only in-range rows, ascending by posted_at
    expected_output = ["in-1", "in-2"]

    # assert
    assert output == expected_output
