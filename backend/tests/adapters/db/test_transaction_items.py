"""Smoke tests for TransactionItem ORM model: FK and cascade delete."""

from __future__ import annotations

from datetime import date

import pytest

from penny.adapters.db.models import (
    DerivedTransaction,
    PlaidTransaction,
    TransactionItem,
)
from penny.db import get_db


def _insert_plaid_txn() -> int:
    """Insert a minimal PlaidTransaction; return its PK."""
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
        plaid_transaction_id: int = plaid_txn.plaid_transaction_id
        session.expunge(plaid_txn)
    return plaid_transaction_id


def _insert_derived_txn(plaid_transaction_id: int) -> int:
    """Insert a DerivedTransaction; return its PK."""
    with get_db().session() as session:
        txn = DerivedTransaction(
            plaid_transaction_id=plaid_transaction_id,
            external_id="derived-001",
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
        )
        session.add(txn)
        session.flush()
        transaction_id: int = txn.transaction_id
        session.expunge(txn)
    return transaction_id


def _insert_transaction_item(transaction_id: int) -> int:
    """Insert a TransactionItem; return its PK."""
    with get_db().session() as session:
        item = TransactionItem(
            transaction_id=transaction_id,
            description="Wireless Mouse",
            amount_cents=2500,
            quantity=1,
            itemization_source="amazon_scrape",
            source_ref="112-0000001-0000001",
        )
        session.add(item)
        session.flush()
        item_id: int = item.item_id
        session.expunge(item)
    return item_id


def _count_items(transaction_id: int) -> int:
    """Return the number of TransactionItems for the given transaction_id."""
    with get_db().session() as session:
        return (
            session.query(TransactionItem)
            .filter_by(transaction_id=transaction_id)
            .count()
        )


def test_transaction_item_fk_and_cascade_delete(
    isolated_db: pytest.FixtureRequest,
) -> None:
    # input / setup
    get_db().create_schema()
    plaid_transaction_id = _insert_plaid_txn()
    transaction_id = _insert_derived_txn(plaid_transaction_id)
    _insert_transaction_item(transaction_id)

    # act: delete the parent DerivedTransaction
    with get_db().session() as session:
        txn = session.get(DerivedTransaction, transaction_id)
        assert txn is not None
        session.delete(txn)

    # expected: TransactionItem rows were cascade-deleted
    expected_item_count = 0

    # assert
    assert _count_items(transaction_id) == expected_item_count
