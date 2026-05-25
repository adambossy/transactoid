"""Tests for scripts/backfill_sign_conventions.py."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from scripts.backfill_sign_conventions import backfill_sign_conventions
from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
from transactoid.services.re_derive import SupportsReDerive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'backfill_sign.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str,
    account_id: str,
    amount_cents: int = -5000,
) -> int:
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id=account_id,
            item_id=None,
            posted_at=date(2026, 3, 1),
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
    amount_cents: int = -5000,
    is_verified: bool = False,
) -> int:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=date(2026, 3, 1),
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


class _StubRunner:
    """Stub that re-inserts derived rows with negated amounts (sign normalization)."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
        new_ids: list[int] = []
        for pid in plaid_ids:
            with self._db.session() as session:
                plaid_row = session.get(PlaidTransaction, pid)
                assert plaid_row is not None
                row = DerivedTransaction(
                    plaid_transaction_id=pid,
                    external_id=f"norm-{pid}",
                    amount_cents=-plaid_row.amount_cents,
                    posted_at=date(2026, 3, 1),
                    is_verified=False,
                )
                session.add(row)
                session.flush()
                new_ids.append(row.transaction_id)
        return new_ids

    async def _categorize_derived(self, derived_ids: list[int]) -> None:
        pass


def _make_factory(db: DB) -> Callable[[DB], SupportsReDerive]:
    """Return a callable that produces a _StubRunner."""

    def factory(inner_db: DB) -> _StubRunner:
        return _StubRunner(db)

    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backfill_golden_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two expense_negative accounts each with unverified rows get re-derived."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-neg-1", "expense_negative", provenance="manual")
    db.set_sign_convention("acct-neg-2", "expense_negative", provenance="manual")

    pid1 = _insert_plaid_txn(
        db, external_id="pt-neg1", account_id="acct-neg-1", amount_cents=-5000
    )
    pid2 = _insert_plaid_txn(
        db, external_id="pt-neg2", account_id="acct-neg-2", amount_cents=-3000
    )
    _insert_derived_txn(db, pid1, external_id="dt-neg1-old", amount_cents=-5000)
    _insert_derived_txn(db, pid2, external_id="dt-neg2-old", amount_cents=-3000)

    output = backfill_sign_conventions(sync_tool_factory=_make_factory(db))

    expected_output = {
        "accounts_processed": 2,
        "accounts_failed": 0,
        "total_deleted": 2,
        "total_new_derived": 2,
        "total_verified_skipped": 0,
    }

    assert output == expected_output

    # Old rows should be gone; new normalized rows should be present.
    new_rows_1 = db.get_derived_by_plaid_id(pid1)
    new_rows_2 = db.get_derived_by_plaid_id(pid2)
    assert len(new_rows_1) == 1
    assert len(new_rows_2) == 1
    assert new_rows_1[0].amount_cents == 5000
    assert new_rows_2[0].amount_cents == 3000


def test_backfill_dry_run_is_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run reports the plan without modifying any rows."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-dry", "expense_negative", provenance="manual")

    pid = _insert_plaid_txn(db, external_id="pt-dry", account_id="acct-dry")
    txn_id = _insert_derived_txn(db, pid, external_id="dt-dry-old", amount_cents=-4000)

    output = backfill_sign_conventions(
        dry_run=True, sync_tool_factory=_make_factory(db)
    )

    # dry-run returns unverified count as total_deleted; no new_derived produced.
    assert output["total_deleted"] == 1
    assert output["total_new_derived"] == 0
    assert output["accounts_processed"] == 1

    # Original row must be untouched.
    row = _fetch_derived(db, txn_id)
    assert row is not None
    assert row.amount_cents == -4000
    assert row.external_id == "dt-dry-old"


def test_backfill_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second run: already-canonical rows are delete+reinserted, no net change."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-idem", "expense_negative", provenance="manual")

    pid = _insert_plaid_txn(db, external_id="pt-idem", account_id="acct-idem")
    _insert_derived_txn(db, pid, external_id="dt-idem-old", amount_cents=-6000)

    first_output = backfill_sign_conventions(sync_tool_factory=_make_factory(db))
    assert first_output["total_deleted"] == 1
    assert first_output["total_new_derived"] == 1

    # Second run: the stub re-derives from plaid_transactions again.
    # The old row is gone (from first run); one unverified row exists from first run.
    second_output = backfill_sign_conventions(sync_tool_factory=_make_factory(db))

    # One unverified row existed → deleted and re-inserted.
    assert second_output["accounts_processed"] == 1
    assert second_output["accounts_failed"] == 0


def test_backfill_per_account_failure_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failing account does not prevent others from completing; exit is non-zero."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-fail", "expense_negative", provenance="manual")
    db.set_sign_convention("acct-ok", "expense_negative", provenance="manual")

    pid_fail = _insert_plaid_txn(
        db, external_id="pt-fail", account_id="acct-fail", amount_cents=-2000
    )
    pid_ok = _insert_plaid_txn(
        db, external_id="pt-ok", account_id="acct-ok", amount_cents=-1000
    )
    _insert_derived_txn(db, pid_fail, external_id="dt-fail-old", amount_cents=-2000)
    _insert_derived_txn(db, pid_ok, external_id="dt-ok-old", amount_cents=-1000)

    call_count = 0

    class _SelectiveErrorRunner:
        """Raises for acct-fail, succeeds (via _StubRunner) for acct-ok."""

        def __init__(self, inner_db: DB) -> None:
            self._db = inner_db
            self._stub = _StubRunner(inner_db)
            nonlocal call_count
            call_count += 1
            self._call_index = call_count

        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            if self._call_index == 1:
                raise RuntimeError("deliberate failure")
            return self._stub._mutate_batch_to_derived(plaid_ids)

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    def selective_factory(inner_db: DB) -> _SelectiveErrorRunner:
        return _SelectiveErrorRunner(inner_db)

    with pytest.raises(SystemExit) as exc_info:
        backfill_sign_conventions(sync_tool_factory=selective_factory)

    assert exc_info.value.code != 0

    # acct-ok should have its row re-derived regardless of acct-fail's failure.
    ok_rows = db.get_derived_by_plaid_id(pid_ok)
    assert len(ok_rows) == 1
    assert ok_rows[0].amount_cents == 1000


def test_backfill_verified_rows_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified rows are untouched; summary reports the preserved count."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-mixed", "expense_negative", provenance="manual")

    pid = _insert_plaid_txn(db, external_id="pt-mixed", account_id="acct-mixed")
    verified_id = _insert_derived_txn(
        db, pid, external_id="dt-verified-old", amount_cents=-7000, is_verified=True
    )
    _insert_derived_txn(
        db, pid, external_id="dt-unverified-old", amount_cents=-7000, is_verified=False
    )

    class _NullRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            return []

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    def null_factory(inner_db: DB) -> _NullRunner:
        return _NullRunner()

    output = backfill_sign_conventions(sync_tool_factory=null_factory)

    assert output["total_verified_skipped"] == 1
    assert output["accounts_processed"] == 1
    assert output["accounts_failed"] == 0

    # Verified row must still exist and be unchanged.
    verified_row = _fetch_derived(db, verified_id)
    assert verified_row is not None
    assert verified_row.amount_cents == -7000
    assert verified_row.is_verified is True


def test_backfill_no_expense_negative_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When there are no expense_negative accounts, returns zero counts immediately."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'backfill_sign.db'}")

    db = create_db(tmp_path)
    db.set_sign_convention("acct-pos", "expense_positive", provenance="manual")

    pid = _insert_plaid_txn(db, external_id="pt-pos", account_id="acct-pos")
    _insert_derived_txn(db, pid, external_id="dt-pos", amount_cents=5000)

    output = backfill_sign_conventions(sync_tool_factory=_make_factory(db))

    expected_output = {
        "accounts_processed": 0,
        "accounts_failed": 0,
        "total_deleted": 0,
        "total_new_derived": 0,
        "total_verified_skipped": 0,
    }

    assert output == expected_output
