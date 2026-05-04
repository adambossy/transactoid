"""Tests for the 'transactoid split' CLI command."""

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
    db = DB(f"sqlite:///{tmp_path / 'split_cli.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB, *, external_id: str = "ext-cli-001", amount_cents: int = 5000
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
    external_id: str = "derived-cli-001",
    amount_cents: int = 5000,
    is_verified: bool = False,
) -> int:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=date(2026, 1, 10),
            is_verified=is_verified,
        )
        session.add(row)
        session.flush()
        txn_id: int = row.transaction_id
    return txn_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_split_cmd_golden_path(tmp_path: Path) -> None:
    """Successful split prints one-line summary and creates new rows."""
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000)

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["split", str(txn_id), "30.00", "20.00"])

    assert result.exit_code == 0
    assert f"Split TXN-{txn_id}" in result.output
    assert "2 parts" in result.output


def test_split_cmd_invalid_precision(tmp_path: Path) -> None:
    """Amounts with >2 decimal places are rejected before DB access."""
    db = create_db(tmp_path)

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["split", "1", "12.345", "37.655"])

    assert result.exit_code != 0
    assert "decimal places" in result.output


def test_split_cmd_verified_error_prints_to_stderr(tmp_path: Path) -> None:
    """SplitError for a verified row exits non-zero with message on stderr."""
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, amount_cents=5000)
    txn_id = _insert_derived_txn(db, plaid_id, amount_cents=5000, is_verified=True)

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["split", str(txn_id), "30.00", "20.00"])

    assert result.exit_code != 0
    assert "verified" in result.stderr


def test_split_cmd_zero_amount_rejected(tmp_path: Path) -> None:
    """Zero amount is rejected (must be strictly positive)."""
    db = create_db(tmp_path)

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["split", "1", "0.00", "50.00"])

    assert result.exit_code != 0
    assert "not positive" in result.stderr


def test_split_cmd_excessive_amount_rejected(tmp_path: Path) -> None:
    """Amounts over $1,000,000 per part are rejected with an overflow error."""
    db = create_db(tmp_path)

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["split", "1", "1000001.00", "500.00"])

    assert result.exit_code != 0
    assert "exceeds the per-part limit" in result.stderr
