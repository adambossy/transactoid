"""Tests for the 'transactoid refund' CLI command."""

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
    db = DB(f"sqlite:///{tmp_path / 'refund_cli.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str,
    amount_cents: int = 5000,
    posted_at: date = date(2026, 1, 10),
    account_id: str = "acct-abc",
) -> int:
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id=account_id,
            item_id=None,
            posted_at=posted_at,
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
    amount_cents: int = 5000,
    posted_at: date = date(2026, 1, 10),
    is_verified: bool = False,
) -> int:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=posted_at,
            is_verified=is_verified,
        )
        session.add(row)
        session.flush()
        txn_id: int = row.transaction_id
    return txn_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_refund_cmd_golden_path(tmp_path: Path) -> None:
    # input
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(db, external_id="orig-plaid", amount_cents=5000)
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived", amount_cents=5000
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
    )

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["refund", str(refund_id), "--of", str(orig_id)])

    assert result.exit_code == 0
    assert f"TXN-{refund_id}" in result.output
    assert f"TXN-{orig_id}" in result.output
    assert "Linked refund" in result.output


def test_refund_cmd_verified_error_prints_to_stderr(tmp_path: Path) -> None:
    """RefundError for a verified row exits non-zero with message on stderr."""
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(db, external_id="orig-plaid-v")
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-v",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-v", is_verified=True
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-v",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )

    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["refund", str(refund_id), "--of", str(orig_id)])

    assert result.exit_code != 0
    assert "verified" in result.stderr


def test_refund_cmd_account_mismatch_warning(tmp_path: Path) -> None:
    # input: refund and original on different accounts
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(
        db, external_id="orig-plaid-mismatch", amount_cents=5000, account_id="acct-one"
    )
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-mismatch",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
        account_id="acct-two",
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-mismatch", amount_cents=5000
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-mismatch",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
    )

    # act
    with patch("transactoid.ui.cli.DB") as mock_db_cls:
        mock_db_cls.return_value = db
        result = runner.invoke(app, ["refund", str(refund_id), "--of", str(orig_id)])

    # assert: operation succeeds
    assert result.exit_code == 0
    # warning appears on stderr
    assert "Warning" in result.stderr
    assert "different accounts" in result.stderr
    # success line still printed to stdout
    assert "Linked refund" in result.output
