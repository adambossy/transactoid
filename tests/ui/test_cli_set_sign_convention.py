"""Tests for the 'transactoid set-sign-convention' CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from transactoid.adapters.db.facade import DB
from transactoid.ui.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'sign_convention_cli.db'}")
    db.create_schema()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_set_sign_convention_golden_path(tmp_path: Path) -> None:
    """Successful set prints confirmation and persists the convention."""
    db = create_db(tmp_path)

    db_url = f"sqlite:///{tmp_path / 'sign_convention_cli.db'}"
    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(
            app, ["set-sign-convention", "acct-001", "expense_negative"]
        )

    assert result.exit_code == 0
    assert "Set account acct-001 -> expense_negative" in result.output

    stored = db.get_sign_convention("acct-001")
    assert stored == "expense_negative"


def test_set_sign_convention_with_notes(tmp_path: Path) -> None:
    """--notes flag is persisted."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'sign_convention_cli.db'}"

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(
            app,
            [
                "set-sign-convention",
                "acct-002",
                "expense_positive",
                "--notes",
                "Chase checking",
            ],
        )

    assert result.exit_code == 0

    rows = db.list_sign_conventions()
    matching = [r for r in rows if r.account_id == "acct-002"]
    assert len(matching) == 1
    assert matching[0].notes == "Chase checking"


def test_set_sign_convention_invalid_convention(tmp_path: Path) -> None:
    """Invalid convention value exits 1 and prints error to stderr."""
    db_url = f"sqlite:///{tmp_path / 'sign_convention_cli.db'}"

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(
            app, ["set-sign-convention", "acct-003", "invalid_value"]
        )

    assert result.exit_code == 1
    assert "expense_positive" in result.output
    assert "expense_negative" in result.output
    assert "invalid_value" in result.output


def test_set_sign_convention_expense_positive_valid(tmp_path: Path) -> None:
    """'expense_positive' is a valid convention."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'sign_convention_cli.db'}"

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(
            app, ["set-sign-convention", "acct-004", "expense_positive"]
        )

    assert result.exit_code == 0
    assert "acct-004" in result.output
    assert "expense_positive" in result.output
    assert db.get_sign_convention("acct-004") == "expense_positive"
