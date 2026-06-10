"""Unit tests for the re_derive_account service function."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from penny.adapters.db.facade import DB
from penny.adapters.db.models import DerivedTransaction, PlaidTransaction
from penny.tools._services.re_derive import (
    ReDeriveResult,
    SupportsReDerive,
    re_derive_account,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str = "pt-001",
    account_id: str = "acct-x",
    amount_cents: int = 3000,
) -> int:
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id=account_id,
            item_id=None,
            posted_at=date(2026, 2, 15),
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
    external_id: str = "dt-001",
    is_verified: bool = False,
) -> int:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=3000,
            posted_at=date(2026, 2, 15),
            is_verified=is_verified,
        )
        session.add(row)
        session.flush()
        txn_id: int = row.transaction_id
    return txn_id


class _StubRunner:
    """No-op stub that inserts one new derived row per plaid_id."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
        new_ids: list[int] = []
        for pid in plaid_ids:
            with self._db.session() as session:
                row = DerivedTransaction(
                    plaid_transaction_id=pid,
                    external_id=f"new-{pid}",
                    amount_cents=3000,
                    posted_at=date(2026, 2, 15),
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


def test_re_derive_raises_for_unknown_account(isolated_db: None) -> None:
    # input
    account_id = "no-such-account"

    # act / assert
    from penny.db import get_db

    db = get_db()
    with pytest.raises(ValueError, match="no transactions found for account"):
        re_derive_account(db, account_id, sync_tool_factory=_make_factory(db))


def test_re_derive_raises_when_no_sign_convention_configured(
    isolated_db: None,
) -> None:
    # input
    account_id = "acct-no-conv"

    # setup: plaid txn exists but no sign convention row
    from penny.db import get_db

    db = get_db()
    _insert_plaid_txn(db, external_id="pt-no-conv", account_id=account_id)

    # act / assert — must raise before any deletion
    with pytest.raises(ValueError, match="no sign convention configured for account"):
        re_derive_account(db, account_id, sync_tool_factory=_make_factory(db))


def test_re_derive_deletes_unverified_rows(isolated_db: None) -> None:
    # input
    account_id = "acct-rd1"

    # setup
    from penny.db import get_db

    db = get_db()
    db.set_sign_convention(account_id, "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="pt-rd1", account_id=account_id)
    _insert_derived_txn(db, plaid_id, external_id="dt-unverified", is_verified=False)

    # act
    output = re_derive_account(db, account_id, sync_tool_factory=_make_factory(db))

    # expected: old unverified row gone, one new row present
    expected_output = ReDeriveResult(
        deleted_count=1,
        new_derived_count=1,
        categorized_count=1,
        verified_skipped=0,
        mutate_failed=False,
        categorize_failed=False,
        failure_message=None,
    )

    # assert
    assert output == expected_output

    current_rows = db.get_derived_by_plaid_id(plaid_id)
    external_ids = {r.external_id for r in current_rows}
    assert "dt-unverified" not in external_ids
    assert f"new-{plaid_id}" in external_ids


def test_re_derive_preserves_verified_rows(isolated_db: None) -> None:
    # input
    account_id = "acct-rd2"

    # setup
    from penny.db import get_db

    db = get_db()
    db.set_sign_convention(account_id, "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="pt-rd2", account_id=account_id)
    verified_id = _insert_derived_txn(
        db, plaid_id, external_id="dt-verified", is_verified=True
    )
    _insert_derived_txn(db, plaid_id, external_id="dt-unverified", is_verified=False)

    class _NullRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            return []

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    def null_factory(inner_db: DB) -> _NullRunner:
        return _NullRunner()

    # act
    output = re_derive_account(db, account_id, sync_tool_factory=null_factory)

    # expected: 1 verified skipped, 0 re-derived
    expected_output = ReDeriveResult(
        deleted_count=1,
        new_derived_count=0,
        categorized_count=0,
        verified_skipped=1,
        mutate_failed=False,
        categorize_failed=False,
        failure_message=None,
    )

    # assert
    assert output == expected_output

    rows = db.get_derived_by_plaid_id(plaid_id)
    ids = {r.transaction_id for r in rows}
    assert verified_id in ids


def test_re_derive_returns_correct_counts_multiple_plaid_txns(
    isolated_db: None,
) -> None:
    # input
    account_id = "acct-rd3"

    # setup
    from penny.db import get_db

    db = get_db()
    db.set_sign_convention(account_id, "expense_positive", provenance="manual")
    pid1 = _insert_plaid_txn(db, external_id="pt-rd3a", account_id=account_id)
    pid2 = _insert_plaid_txn(db, external_id="pt-rd3b", account_id=account_id)
    _insert_derived_txn(db, pid1, external_id="dt-rd3a", is_verified=False)
    _insert_derived_txn(db, pid2, external_id="dt-rd3b", is_verified=False)

    # act
    output = re_derive_account(db, account_id, sync_tool_factory=_make_factory(db))

    # expected: 2 re-derived, 0 skipped
    expected_output = ReDeriveResult(
        deleted_count=2,
        new_derived_count=2,
        categorized_count=2,
        verified_skipped=0,
        mutate_failed=False,
        categorize_failed=False,
        failure_message=None,
    )

    # assert
    assert output == expected_output


def test_re_derive_returns_mutate_failed_result_on_mutate_error(
    isolated_db: None,
) -> None:
    # input
    account_id = "acct-mut-fail"

    # setup
    from penny.db import get_db

    db = get_db()
    db.set_sign_convention(account_id, "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="pt-mut-fail", account_id=account_id)
    _insert_derived_txn(db, plaid_id, external_id="dt-mut-fail", is_verified=False)

    class _MutateErrorRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            raise RuntimeError("mutate exploded")

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    def error_factory(inner_db: DB) -> _MutateErrorRunner:
        return _MutateErrorRunner()

    # act
    output = re_derive_account(db, account_id, sync_tool_factory=error_factory)

    # expected
    expected_output = ReDeriveResult(
        deleted_count=1,
        new_derived_count=0,
        categorized_count=0,
        verified_skipped=0,
        mutate_failed=True,
        categorize_failed=False,
        failure_message="mutate exploded",
    )

    # assert
    assert output == expected_output


def test_re_derive_returns_categorize_failed_result_on_categorize_error(
    isolated_db: None,
) -> None:
    # input
    account_id = "acct-cat-fail"

    # setup
    from penny.db import get_db

    db = get_db()
    db.set_sign_convention(account_id, "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="pt-cat-fail", account_id=account_id)
    _insert_derived_txn(db, plaid_id, external_id="dt-cat-fail", is_verified=False)

    class _CatErrorRunner:
        def __init__(self, inner_db: DB) -> None:
            self._db = inner_db

        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            new_ids: list[int] = []
            for pid in plaid_ids:
                with self._db.session() as session:
                    row = DerivedTransaction(
                        plaid_transaction_id=pid,
                        external_id=f"cat-err-{pid}",
                        amount_cents=3000,
                        posted_at=date(2026, 2, 15),
                        is_verified=False,
                    )
                    session.add(row)
                    session.flush()
                    new_ids.append(row.transaction_id)
            return new_ids

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            raise RuntimeError("categorize exploded")

    def cat_error_factory(inner_db: DB) -> _CatErrorRunner:
        return _CatErrorRunner(inner_db)

    # act
    output = re_derive_account(db, account_id, sync_tool_factory=cat_error_factory)

    # expected: mutate succeeded (1 new row), categorize failed
    expected_output = ReDeriveResult(
        deleted_count=1,
        new_derived_count=1,
        categorized_count=0,
        verified_skipped=0,
        mutate_failed=False,
        categorize_failed=True,
        failure_message="categorize exploded",
    )

    # assert
    assert output == expected_output
