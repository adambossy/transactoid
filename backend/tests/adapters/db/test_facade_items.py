"""Tests for DB.bulk_insert_transaction_items: bulk-only (no N+1) insert."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    DerivedTransaction,
    PlaidTransaction,
    TransactionItem,
)
from penny.tools._services.mutation_plugin import TransactionItemPayload


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(db: DB) -> int:
    """Insert a minimal PlaidTransaction; return its PK."""
    with db.session() as session:
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
        plaid_id: int = plaid_txn.plaid_transaction_id
    return plaid_id


def _insert_derived_txn(
    db: DB, plaid_transaction_id: int, *, external_id: str = "derived-001"
) -> int:
    """Insert a DerivedTransaction; return its PK."""
    with db.session() as session:
        txn = DerivedTransaction(
            plaid_transaction_id=plaid_transaction_id,
            external_id=external_id,
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
        )
        session.add(txn)
        session.flush()
        transaction_id: int = txn.transaction_id
    return transaction_id


def _count_items(db: DB) -> int:
    """Count all TransactionItem rows in the DB."""
    with db.session() as session:
        return session.query(TransactionItem).count()


def test_bulk_insert_transaction_items_single_call(tmp_path: Path) -> None:
    """bulk_insert_transaction_items issues a single add_all for N items (no N+1)."""
    # input
    db = _create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id_1 = _insert_derived_txn(db, plaid_id, external_id="derived-001")
    txn_id_2 = _insert_derived_txn(db, plaid_id, external_id="derived-002")

    items_1 = [
        TransactionItemPayload(
            description="Mouse",
            amount_cents=2500,
            quantity=1,
            itemization_source="amazon_scrape",
            source_ref="ORDER-001",
        ),
    ]
    items_2 = [
        TransactionItemPayload(
            description="Keyboard",
            amount_cents=1500,
            quantity=1,
            itemization_source="amazon_scrape",
            source_ref="ORDER-001",
        ),
        TransactionItemPayload(
            description="Hub",
            amount_cents=1000,
            quantity=2,
            itemization_source="amazon_scrape",
            source_ref="ORDER-001",
        ),
    ]
    items_by_transaction = [(txn_id_1, items_1), (txn_id_2, items_2)]

    # Patch session.add_all to count invocations
    with db.session() as session:
        original_add_all = session.add_all

        with patch.object(session, "add_all", wraps=original_add_all) as mock_add_all:
            db._bulk_insert_transaction_items(session, items_by_transaction)
            # assert: exactly one add_all call for all 3 items
            assert mock_add_all.call_count == 1
            inserted_rows = mock_add_all.call_args[0][0]
            assert len(inserted_rows) == 3

    # Verify rows are in the DB
    assert _count_items(db) == 3


def test_bulk_insert_transaction_items_empty_noop(tmp_path: Path) -> None:
    """Empty items_by_transaction is a no-op."""
    db = _create_db(tmp_path)

    # act
    db.bulk_insert_transaction_items([])

    # assert: nothing in DB
    assert _count_items(db) == 0


def test_bulk_insert_transaction_items_public_facade(tmp_path: Path) -> None:
    """Public facade bulk_insert_transaction_items writes all items correctly."""
    # input
    db = _create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id = _insert_derived_txn(db, plaid_id)

    item_payloads = [
        TransactionItemPayload(
            description="Widget A",
            amount_cents=3000,
            quantity=1,
            itemization_source="manual",
        ),
        TransactionItemPayload(
            description="Widget B",
            amount_cents=2000,
            quantity=3,
            itemization_source="manual",
        ),
    ]

    # act
    db.bulk_insert_transaction_items([(txn_id, item_payloads)])

    # expected: 2 rows in DB
    expected_count = 2

    # assert
    assert _count_items(db) == expected_count
