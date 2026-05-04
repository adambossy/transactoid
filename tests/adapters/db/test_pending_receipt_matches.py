"""Smoke tests for PendingReceiptMatch ORM model: cascade delete."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import (
    DerivedTransaction,
    EmailReceipt,
    PendingReceiptMatch,
    PlaidTransaction,
)


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(db: DB) -> int:
    """Insert a minimal PlaidTransaction; return its PK."""
    with db.session() as session:
        plaid_txn = PlaidTransaction(
            external_id="ext-prm-001",
            source="PLAID",
            account_id="acct-prm",
            item_id=None,
            posted_at=date(2026, 3, 15),
            amount_cents=4999,
            currency="USD",
        )
        session.add(plaid_txn)
        session.flush()
        plaid_transaction_id: int = plaid_txn.plaid_transaction_id
        session.expunge(plaid_txn)
    return plaid_transaction_id


def _insert_derived_txn(db: DB, plaid_transaction_id: int) -> int:
    """Insert a DerivedTransaction; return its PK."""
    with db.session() as session:
        txn = DerivedTransaction(
            plaid_transaction_id=plaid_transaction_id,
            external_id="derived-prm-001",
            amount_cents=4999,
            posted_at=date(2026, 3, 15),
        )
        session.add(txn)
        session.flush()
        transaction_id: int = txn.transaction_id
        session.expunge(txn)
    return transaction_id


def _insert_email_receipt(db: DB, message_id: str) -> None:
    """Insert an EmailReceipt."""
    with db.session() as session:
        receipt = EmailReceipt(message_id=message_id)
        session.add(receipt)
        session.flush()
        session.expunge(receipt)


def _insert_pending_match(db: DB, message_id: str, candidate_txn_id: int) -> int:
    """Insert a PendingReceiptMatch; return its PK."""
    with db.session() as session:
        match = PendingReceiptMatch(
            message_id=message_id,
            candidate_txn_id=candidate_txn_id,
            amount_cents=4999,
            date_lag_days=2,
            match_score=0.72,
            status="pending",
        )
        session.add(match)
        session.flush()
        pending_id: int = match.pending_id
        session.expunge(match)
    return pending_id


def _count_pending_matches(db: DB, pending_id: int) -> int:
    """Return the number of PendingReceiptMatch rows with the given PK."""
    with db.session() as session:
        return (
            session.query(PendingReceiptMatch).filter_by(pending_id=pending_id).count()
        )


def test_pending_receipt_match_cascade_delete(
    tmp_path: Path,
) -> None:
    # input
    message_id = "msg-cascade-001"
    db = _create_db(tmp_path)

    # setup
    plaid_txn_id = _insert_plaid_txn(db)
    txn_id = _insert_derived_txn(db, plaid_txn_id)
    _insert_email_receipt(db, message_id)
    pending_id = _insert_pending_match(db, message_id, txn_id)

    # act: delete the parent EmailReceipt
    with db.session() as session:
        receipt = session.query(EmailReceipt).filter_by(message_id=message_id).one()
        session.delete(receipt)

    # expected: PendingReceiptMatch was cascade-deleted
    expected_count = 0

    # assert
    assert _count_pending_matches(db, pending_id) == expected_count
