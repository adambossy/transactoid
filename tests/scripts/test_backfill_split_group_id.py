"""Tests for scripts/backfill_split_group_id.py."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.backfill_split_group_id import backfill_split_group_ids
from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB."""
    db = DB(f"sqlite:///{tmp_path / 'backfill_test.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB, *, external_id: str = "ext-001", amount_cents: int = 5000
) -> int:
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id="acct-abc",
            item_id=None,
            posted_at=date(2026, 1, 10),
            amount_cents=amount_cents,
            currency="USD",
        )
        session.add(txn)
        session.flush()
        plaid_id: int = txn.plaid_transaction_id
    return plaid_id


def _insert_derived_txn(
    db: DB,
    plaid_id: int,
    *,
    external_id: str,
    amount_cents: int = 2500,
    split_group_id: str | None = None,
    is_verified: bool = False,
) -> int:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=date(2026, 1, 10),
            split_group_id=split_group_id,
            is_verified=is_verified,
        )
        session.add(row)
        session.flush()
        txn_id: int = row.transaction_id
    return txn_id


def _fetch_derived(db: DB, txn_id: int) -> DerivedTransaction | None:
    with db.session() as session:
        row = session.get(DerivedTransaction, txn_id)
        if row is not None:
            session.expunge(row)
        return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backfill_stamps_amazon_split_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows sharing a plaid_transaction_id get a shared split_group_id."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_test.db'}")

    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id_a = _insert_derived_txn(db, plaid_id, external_id="item:0")
    txn_id_b = _insert_derived_txn(db, plaid_id, external_id="item:1")

    result = backfill_split_group_ids()

    assert result["groups_updated"] == 1
    assert result["rows_updated"] == 2

    row_a = _fetch_derived(db, txn_id_a)
    row_b = _fetch_derived(db, txn_id_b)
    assert row_a is not None and row_b is not None

    assert row_a.split_group_id is not None
    assert row_a.split_group_id == row_b.split_group_id
    assert row_a.split_source == "amazon_mutation"
    assert row_b.split_source == "amazon_mutation"
    # split_index stable by external_id sort: "item:0" < "item:1"
    assert row_a.split_index == 0
    assert row_b.split_index == 1


def test_backfill_skips_single_derived_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plaid txns with only one derived row are not modified."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_test.db'}")

    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id = _insert_derived_txn(db, plaid_id, external_id="only-row")

    result = backfill_split_group_ids()

    assert result["groups_updated"] == 0
    assert result["rows_updated"] == 0

    row = _fetch_derived(db, txn_id)
    assert row is not None
    assert row.split_group_id is None


def test_backfill_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running the backfill twice produces the same result; no duplicate work."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_test.db'}")

    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id_a = _insert_derived_txn(db, plaid_id, external_id="item:0")
    txn_id_b = _insert_derived_txn(db, plaid_id, external_id="item:1")

    result1 = backfill_split_group_ids()
    row_a_after_first = _fetch_derived(db, txn_id_a)
    assert row_a_after_first is not None
    group_id_after_first = row_a_after_first.split_group_id

    result2 = backfill_split_group_ids()

    # Second run is a no-op.
    assert result2["groups_updated"] == 0
    assert result2["rows_updated"] == 0

    # group_id unchanged.
    row_a_after_second = _fetch_derived(db, txn_id_a)
    row_b_after_second = _fetch_derived(db, txn_id_b)
    assert row_a_after_second is not None and row_b_after_second is not None
    assert row_a_after_second.split_group_id == group_id_after_first
    assert row_b_after_second.split_group_id == group_id_after_first

    assert result1["groups_updated"] == 1


def test_backfill_skips_verified_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified rows in a split group are skipped with a warning to stderr."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_test.db'}")

    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    txn_id_a = _insert_derived_txn(db, plaid_id, external_id="item:0", is_verified=True)
    txn_id_b = _insert_derived_txn(db, plaid_id, external_id="item:1")

    result = backfill_split_group_ids()

    # groups_updated counts the group (2 siblings), rows_updated counts only the
    # non-verified row (item:1) since item:0 is skipped.
    assert result["groups_updated"] == 1
    assert result["rows_updated"] == 1

    row_a = _fetch_derived(db, txn_id_a)
    row_b = _fetch_derived(db, txn_id_b)
    assert row_a is not None and row_b is not None

    # Verified row is unchanged.
    assert row_a.split_group_id is None
    # Unverified sibling gets stamped.
    assert row_b.split_group_id is not None
    assert row_b.split_source == "amazon_mutation"


def test_backfill_per_row_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running after a user split exists preserves the user-split UUID."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_test.db'}")

    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db)
    user_split_group = "user-defined-uuid-1234"
    # Simulate a row that already has a user-assigned split_group_id.
    txn_id_a = _insert_derived_txn(
        db, plaid_id, external_id="item:0", split_group_id=user_split_group
    )
    txn_id_b = _insert_derived_txn(db, plaid_id, external_id="item:1")

    result = backfill_split_group_ids()

    # One group processed, but only the unstamped row gets a new UUID.
    assert result["groups_updated"] == 1
    assert result["rows_updated"] == 1

    row_a = _fetch_derived(db, txn_id_a)
    row_b = _fetch_derived(db, txn_id_b)
    assert row_a is not None and row_b is not None

    # The user-assigned UUID must not be overwritten.
    assert row_a.split_group_id == user_split_group
    # The previously-unstamped sibling gets a new UUID.
    assert row_b.split_group_id is not None
    assert row_b.split_group_id != user_split_group
