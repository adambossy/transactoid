"""Tests for split_transaction service."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
from transactoid.errors import SplitError
from transactoid.services.split import split_transaction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str = "ext-001",
    amount_cents: int = 5000,
    posted_at: date = date(2026, 1, 10),
) -> int:
    """Insert a minimal PlaidTransaction; return its PK."""
    with db.session() as session:
        plaid_txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id="acct-abc",
            item_id=None,
            posted_at=posted_at,
            amount_cents=amount_cents,
            currency="USD",
            merchant_descriptor="Test Merchant",
        )
        session.add(plaid_txn)
        session.flush()
        plaid_id: int = plaid_txn.plaid_transaction_id
    return plaid_id


def _insert_derived_txn(
    db: DB,
    plaid_transaction_id: int,
    *,
    external_id: str = "derived-001",
    amount_cents: int = 5000,
    is_verified: bool = False,
) -> int:
    """Insert a DerivedTransaction; return its PK."""
    with db.session() as session:
        txn = DerivedTransaction(
            plaid_transaction_id=plaid_transaction_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=date(2026, 1, 10),
            is_verified=is_verified,
        )
        session.add(txn)
        session.flush()
        txn_id: int = txn.transaction_id
    return txn_id


def _fetch_derived_by_id(db: DB, transaction_id: int) -> DerivedTransaction | None:
    """Return the DerivedTransaction row or None."""
    with db.session() as session:
        row = session.get(DerivedTransaction, transaction_id)
        if row is not None:
            session.expunge(row)
        return row


def _count_derived_for_plaid(db: DB, plaid_transaction_id: int) -> int:
    """Count derived rows for a given plaid transaction."""
    with db.session() as session:
        return (
            session.query(DerivedTransaction)
            .filter_by(plaid_transaction_id=plaid_transaction_id)
            .count()
        )


def _as_dict(row: DerivedTransaction) -> dict[str, object]:
    """Extract split-relevant fields for equality checks."""
    return {
        "amount_cents": row.amount_cents,
        "split_source": row.split_source,
        "split_index": row.split_index,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_split_transaction_two_way(tmp_path: Path) -> None:
    # input
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)
    parts = [3000, 2000]

    # act
    new_ids = split_transaction(db, txn_id, parts)

    # expected: two new rows with correct amounts/provenance
    assert len(new_ids) == 2
    row0 = _fetch_derived_by_id(db, new_ids[0])
    row1 = _fetch_derived_by_id(db, new_ids[1])

    assert row0 is not None
    assert row1 is not None

    expected_row0 = {
        "amount_cents": 3000,
        "split_source": "user_split",
        "split_index": 0,
    }
    expected_row1 = {
        "amount_cents": 2000,
        "split_source": "user_split",
        "split_index": 1,
    }

    assert _as_dict(row0) == expected_row0
    assert _as_dict(row1) == expected_row1

    # Both share the same non-null split_group_id
    assert row0.split_group_id is not None
    assert row0.split_group_id == row1.split_group_id

    # The derived rows that exist all belong to the split; none have amount=5000
    all_derived = _count_derived_for_plaid(db, plaid_id)
    assert all_derived == 2


def test_split_transaction_three_way(tmp_path: Path) -> None:
    # input
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=9000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=9000)
    parts = [3000, 4000, 2000]

    # act
    new_ids = split_transaction(db, txn_id, parts)

    # expected
    assert len(new_ids) == 3
    rows = [_fetch_derived_by_id(db, nid) for nid in new_ids]
    assert all(r is not None for r in rows)
    # All share the same split_group_id
    split_group_ids = {r.split_group_id for r in rows if r is not None}
    assert len(split_group_ids) == 1
    group_id = split_group_ids.pop()
    assert group_id is not None

    amounts = [r.amount_cents for r in rows if r is not None]
    assert amounts == parts


def test_split_transaction_not_found(tmp_path: Path) -> None:
    db = create_db(tmp_path)

    with pytest.raises(SplitError, match="transaction 9999 not found"):
        split_transaction(db, 9999, [2500, 2500])


def test_split_transaction_verified_rejection(tmp_path: Path) -> None:
    # input
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000, is_verified=True)

    # act + assert
    with pytest.raises(SplitError, match="is verified and cannot be modified"):
        split_transaction(db, txn_id, [3000, 2000])


def test_split_transaction_amazon_gated_rejection(tmp_path: Path) -> None:
    # input: seed an amazon_orders row that matches the plaid transaction
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(
        db,
        amount_cents=5000,
        posted_at=date(2026, 1, 10),
        external_id="amazon-ext-001",
    )
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    # Seed an amazon_orders row with matching total and date within lag window
    profile = db.create_amazon_login_profile(
        profile_key="primary", display_name="Primary"
    )
    db.upsert_amazon_order(
        order_id="113-1234567-1234567",
        order_date=date(2026, 1, 8),  # 2 days before posted_at → within 30d lag
        order_total_cents=5000,
        profile_id=profile.profile_id,
    )

    # act + assert
    with pytest.raises(SplitError, match="is part of Amazon order"):
        split_transaction(db, txn_id, [3000, 2000])


def test_split_transaction_amount_mismatch_rejection(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    with pytest.raises(SplitError, match="they must sum exactly"):
        split_transaction(db, txn_id, [3000, 1000])  # sums to 4000, not 5000


def test_split_transaction_single_part_rejection(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    with pytest.raises(SplitError, match="at least 2 parts"):
        split_transaction(db, txn_id, [5000])


def test_split_transaction_zero_part_rejection(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    with pytest.raises(SplitError, match="all parts must be > 0"):
        split_transaction(db, txn_id, [5000, 0])


def test_split_transaction_negative_part_rejection(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    with pytest.raises(SplitError, match="all parts must be > 0"):
        split_transaction(db, txn_id, [6000, -1000])


def test_split_transaction_atomicity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the write fails mid-way, the original row must be preserved."""
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    original_add = db._session_factory.class_.add

    call_count = 0

    def failing_add(self, instance):  # noqa: ANN001
        nonlocal call_count
        if isinstance(instance, DerivedTransaction):
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("simulated mid-write failure")
        original_add(self, instance)

    monkeypatch.setattr(db._session_factory.class_, "add", failing_add)

    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        split_transaction(db, txn_id, [3000, 2000])

    # The session rolled back — original row must still exist.
    # Unmonkeypatch before querying.
    monkeypatch.undo()

    surviving = _fetch_derived_by_id(db, txn_id)
    assert surviving is not None
    assert surviving.amount_cents == 5000

    # No orphaned split rows.
    with db.session() as session:
        split_rows = (
            session.query(DerivedTransaction)
            .filter(DerivedTransaction.split_source == "user_split")
            .count()
        )
    assert split_rows == 0
