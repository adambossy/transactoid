"""Tests for per-transaction recategorization (Tier 1).

Covers the plan's verification cases:
- smoke: a single row is updated and an audit event is written;
- a subsequent ``recategorize_merchant`` skips the now-verified row;
- round-trip: recategorizing twice yields two events with the correct
  from/to category chain.
"""

from __future__ import annotations

from datetime import date

import pytest

from penny.adapters.db.models import (
    Category,
    DerivedTransaction,
    Merchant,
    PlaidTransaction,
    TransactionCategoryEvent,
)
from penny.db import get_db


def _insert_category(key: str, name: str) -> int:
    with get_db().session() as session:
        category = Category(key=key, name=name)
        session.add(category)
        session.flush()
        category_id: int = category.category_id
        session.expunge(category)
    return category_id


def _insert_merchant(normalized_name: str) -> int:
    with get_db().session() as session:
        merchant = Merchant(normalized_name=normalized_name)
        session.add(merchant)
        session.flush()
        merchant_id: int = merchant.merchant_id
        session.expunge(merchant)
    return merchant_id


def _insert_txn(merchant_id: int, category_id: int) -> int:
    """Insert a plaid + derived txn already categorized; return derived PK."""
    with get_db().session() as session:
        plaid_txn = PlaidTransaction(
            external_id="ext-001",
            source="PLAID",
            account_id="acct-abc",
            item_id=None,
            posted_at=date(2026, 1, 10),
            amount_cents=5000,
            currency="USD",
        )
        session.add(plaid_txn)
        session.flush()

        txn = DerivedTransaction(
            plaid_transaction_id=plaid_txn.plaid_transaction_id,
            external_id="derived-001",
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
            merchant_id=merchant_id,
            category_id=category_id,
            category_method="llm",
            category_model="gpt-test",
            category_assigned_at=date(2026, 1, 10),
        )
        session.add(txn)
        session.flush()
        transaction_id: int = txn.transaction_id
        session.expunge(txn)
    return transaction_id


def _get_txn(transaction_id: int) -> DerivedTransaction:
    with get_db().session() as session:
        txn = session.get(DerivedTransaction, transaction_id)
        assert txn is not None
        session.expunge(txn)
    return txn


def _events(transaction_id: int) -> list[TransactionCategoryEvent]:
    with get_db().session() as session:
        rows = (
            session.query(TransactionCategoryEvent)
            .filter(TransactionCategoryEvent.transaction_id == transaction_id)
            .order_by(TransactionCategoryEvent.event_id.asc())
            .all()
        )
        for row in rows:
            session.expunge(row)
    return rows


def test_recategorize_transaction_updates_row_and_writes_event(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    groceries = _insert_category("food.groceries", "Groceries")
    restaurants = _insert_category("food.restaurants", "Restaurants")
    merchant_id = _insert_merchant("acme")
    txn_id = _insert_txn(merchant_id, groceries)

    result = get_db().recategorize_transaction(
        transaction_id=txn_id,
        category_id=restaurants,
        reason="user fix",
        verify=True,
    )

    assert result["updated"] is True
    assert result["event_id"] is not None

    txn = _get_txn(txn_id)
    assert txn.category_id == restaurants
    assert txn.category_method == "manual"
    assert txn.category_model is None
    assert txn.is_verified is True

    events = _events(txn_id)
    assert len(events) == 1
    assert events[0].from_category_key == "food.groceries"
    assert events[0].to_category_key == "food.restaurants"
    assert events[0].method == "manual"
    assert events[0].recategorization_reason == "user fix"


def test_recategorize_merchant_skips_verified_manual_fix(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    groceries = _insert_category("food.groceries", "Groceries")
    restaurants = _insert_category("food.restaurants", "Restaurants")
    merchant_id = _insert_merchant("acme")
    txn_id = _insert_txn(merchant_id, groceries)

    # Manually fix the one transaction (marks it verified by default).
    get_db().recategorize_transaction(
        transaction_id=txn_id,
        category_id=restaurants,
        verify=True,
    )

    # A bulk merchant recategorization must skip the verified row.
    updated = get_db().recategorize_merchant(merchant_id, groceries)
    assert updated == 0

    txn = _get_txn(txn_id)
    assert txn.category_id == restaurants  # unchanged by the bulk op


def test_recategorize_transaction_round_trip_chains_events(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    groceries = _insert_category("food.groceries", "Groceries")
    restaurants = _insert_category("food.restaurants", "Restaurants")
    merchant_id = _insert_merchant("acme")
    txn_id = _insert_txn(merchant_id, groceries)

    get_db().recategorize_transaction(
        transaction_id=txn_id, category_id=restaurants, verify=True
    )
    get_db().recategorize_transaction(
        transaction_id=txn_id, category_id=groceries, verify=True
    )

    events = _events(txn_id)
    assert len(events) == 2
    assert (events[0].from_category_key, events[0].to_category_key) == (
        "food.groceries",
        "food.restaurants",
    )
    assert (events[1].from_category_key, events[1].to_category_key) == (
        "food.restaurants",
        "food.groceries",
    )


def test_recategorize_transaction_missing_row_raises(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    restaurants = _insert_category("food.restaurants", "Restaurants")

    with pytest.raises(ValueError, match="does not exist"):
        get_db().recategorize_transaction(transaction_id=99999, category_id=restaurants)


def test_recategorize_transaction_no_verify_preserves_flag(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    groceries = _insert_category("food.groceries", "Groceries")
    restaurants = _insert_category("food.restaurants", "Restaurants")
    merchant_id = _insert_merchant("acme")
    txn_id = _insert_txn(merchant_id, groceries)

    # verify=False must leave is_verified untouched (it starts False).
    get_db().recategorize_transaction(
        transaction_id=txn_id, category_id=restaurants, verify=False
    )

    txn = _get_txn(txn_id)
    assert txn.is_verified is False
    assert txn.category_id == restaurants
