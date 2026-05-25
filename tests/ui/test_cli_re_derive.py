"""Tests for the 'transactoid re-derive' CLI command."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
from transactoid.ui.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 're_derive_cli.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str = "ext-001",
    account_id: str = "acct-abc",
    amount_cents: int = 4200,
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
    external_id: str = "drv-001",
    amount_cents: int = 4200,
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


def _count_derived(db: DB, plaid_id: int) -> int:
    rows = db.get_derived_by_plaid_id(plaid_id)
    return len(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_re_derive_unknown_account_exits_nonzero(tmp_path: Path) -> None:
    """Exits 1 with an error message when account_id has no transactions."""
    create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(app, ["re-derive", "--account-id", "no-such-acct"])

    assert result.exit_code == 1
    assert "no-such-acct" in result.output


def test_re_derive_no_sign_convention_exits_nonzero(tmp_path: Path) -> None:
    """Exits 1 with guidance when the account has no sign convention configured."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    _insert_plaid_txn(db, external_id="ext-nc", account_id="acct-nc")

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(app, ["re-derive", "--account-id", "acct-nc"])

    assert result.exit_code == 1
    assert "no sign convention configured" in result.output
    assert "acct-nc" in result.output


def test_re_derive_golden_path_unverified(tmp_path: Path) -> None:
    """Re-derive replaces unverified rows and prints summary."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    db.set_sign_convention("acct-g1", "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="ext-g1", account_id="acct-g1")
    _insert_derived_txn(db, plaid_id, external_id="drv-g1", is_verified=False)

    # Inject a stub sync tool that mimics mutation (returns new derived IDs)
    # and a no-op categorize, so we don't need real Plaid/OpenAI credentials.
    class _StubRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            new_ids: list[int] = []
            for pid in plaid_ids:
                with db.session() as session:
                    row = DerivedTransaction(
                        plaid_transaction_id=pid,
                        external_id=f"re-drv-{pid}",
                        amount_cents=4200,
                        posted_at=date(2026, 3, 1),
                        is_verified=False,
                    )
                    session.add(row)
                    session.flush()
                    new_ids.append(row.transaction_id)
            return new_ids

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    stub = _StubRunner()

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        with patch(
            "transactoid.services.re_derive._default_sync_tool",
            return_value=stub,
        ):
            result = runner.invoke(app, ["re-derive", "--account-id", "acct-g1"])

    assert result.exit_code == 0
    assert "Re-derived" in result.output
    assert "acct-g1" in result.output
    assert "verified rows preserved" in result.output

    # The old unverified row is gone; the new re-derived row exists
    derived_rows = db.get_derived_by_plaid_id(plaid_id)
    external_ids = {r.external_id for r in derived_rows}
    assert "drv-g1" not in external_ids
    assert f"re-drv-{plaid_id}" in external_ids


def test_re_derive_preserves_verified_rows(tmp_path: Path) -> None:
    """Verified rows are not deleted and appear in the preserved count."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    db.set_sign_convention("acct-v1", "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="ext-v1", account_id="acct-v1")
    verified_id = _insert_derived_txn(
        db, plaid_id, external_id="drv-verified", is_verified=True
    )

    class _StubRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            return []

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    stub = _StubRunner()

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        with patch(
            "transactoid.services.re_derive._default_sync_tool",
            return_value=stub,
        ):
            result = runner.invoke(app, ["re-derive", "--account-id", "acct-v1"])

    assert result.exit_code == 0
    assert "1 verified rows preserved" in result.output

    # Verified row still exists
    derived_rows = db.get_derived_by_plaid_id(plaid_id)
    ids = {r.transaction_id for r in derived_rows}
    assert verified_id in ids


def test_re_derive_mutate_failure_exits_nonzero(tmp_path: Path) -> None:
    """Mutate failure prints recovery guidance to stderr and exits 1."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    db.set_sign_convention("acct-mf", "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="ext-mf", account_id="acct-mf")
    _insert_derived_txn(db, plaid_id, external_id="drv-mf", is_verified=False)

    class _MutateErrorRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            raise RuntimeError("mutation failed hard")

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            pass

    stub = _MutateErrorRunner()

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        with patch(
            "transactoid.services.re_derive._default_sync_tool",
            return_value=stub,
        ):
            result = runner.invoke(app, ["re-derive", "--account-id", "acct-mf"])

    assert result.exit_code == 1
    assert "Re-derive incomplete" in result.output
    assert "mutation failed hard" in result.output
    assert "acct-mf" in result.output


def test_re_derive_categorize_failure_exits_nonzero(tmp_path: Path) -> None:
    """Categorize failure prints recovery guidance to stderr and exits 1."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 're_derive_cli.db'}"

    db.set_sign_convention("acct-cf", "expense_positive", provenance="manual")
    plaid_id = _insert_plaid_txn(db, external_id="ext-cf", account_id="acct-cf")
    _insert_derived_txn(db, plaid_id, external_id="drv-cf", is_verified=False)

    class _CatErrorRunner:
        def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
            new_ids: list[int] = []
            for pid in plaid_ids:
                with db.session() as session:
                    row = DerivedTransaction(
                        plaid_transaction_id=pid,
                        external_id=f"cat-err-{pid}",
                        amount_cents=4200,
                        posted_at=date(2026, 3, 1),
                        is_verified=False,
                    )
                    session.add(row)
                    session.flush()
                    new_ids.append(row.transaction_id)
            return new_ids

        async def _categorize_derived(self, derived_ids: list[int]) -> None:
            raise RuntimeError("categorize blew up")

    stub = _CatErrorRunner()

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        with patch(
            "transactoid.services.re_derive._default_sync_tool",
            return_value=stub,
        ):
            result = runner.invoke(app, ["re-derive", "--account-id", "acct-cf"])

    assert result.exit_code == 1
    assert "categorization failed" in result.output
    assert "categorize blew up" in result.output
    assert "transactoid categorize" in result.output
