"""Tests for DB.set_transactions_visibility and the is_hidden default."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import DerivedTransaction, PlaidTransaction


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_derived_txn(db: DB, *, external_id: str) -> int:
    """Insert a PlaidTransaction + DerivedTransaction; return the derived PK."""
    with db.session() as session:
        plaid_txn = PlaidTransaction(
            external_id=f"plaid-{external_id}",
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
            external_id=external_id,
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
        )
        session.add(txn)
        session.flush()
        return txn.transaction_id


def _is_hidden(db: DB, transaction_id: int) -> bool:
    with db.session() as session:
        txn = session.get(DerivedTransaction, transaction_id)
        assert txn is not None
        return txn.is_hidden


def test_is_hidden_defaults_to_false(tmp_path: Path) -> None:
    """A freshly inserted derived transaction is not hidden."""
    db = _create_db(tmp_path)
    txn_id = _insert_derived_txn(db, external_id="d-1")
    assert _is_hidden(db, txn_id) is False


def test_set_transactions_visibility_hides_and_unhides(tmp_path: Path) -> None:
    """set_transactions_visibility flips the flag both directions and counts rows."""
    db = _create_db(tmp_path)
    a = _insert_derived_txn(db, external_id="d-1")
    b = _insert_derived_txn(db, external_id="d-2")

    assert db.set_transactions_visibility([a, b], True) == 2
    assert _is_hidden(db, a) is True
    assert _is_hidden(db, b) is True

    assert db.set_transactions_visibility([a], False) == 1
    assert _is_hidden(db, a) is False
    assert _is_hidden(db, b) is True


def test_set_transactions_visibility_empty_list(tmp_path: Path) -> None:
    """An empty id list updates nothing."""
    db = _create_db(tmp_path)
    assert db.set_transactions_visibility([], True) == 0


def test_set_transactions_visibility_unknown_id(tmp_path: Path) -> None:
    """Unknown ids match no rows and report zero updates."""
    db = _create_db(tmp_path)
    assert db.set_transactions_visibility([999_999], True) == 0
