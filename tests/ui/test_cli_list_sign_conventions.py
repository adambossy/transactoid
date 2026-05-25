"""Tests for the 'transactoid list-sign-conventions' CLI command."""

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
    db = DB(f"sqlite:///{tmp_path / 'list_sign_conv.db'}")
    db.create_schema()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_sign_conventions_empty(tmp_path: Path) -> None:
    """No rows: prints empty message and exits 0."""
    create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'list_sign_conv.db'}"

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(app, ["list-sign-conventions"])

    assert result.exit_code == 0
    assert "No sign conventions configured." in result.output


def test_list_sign_conventions_multiple_rows(tmp_path: Path) -> None:
    """Multiple rows are shown, ordered by provenance then account_id."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'list_sign_conv.db'}"

    db.set_sign_convention(
        "z-acct", "expense_negative", provenance="manual", notes="Z note"
    )
    db.set_sign_convention(
        "a-acct", "expense_positive", provenance="manual", notes="A note"
    )
    db.set_sign_convention(
        "b-acct", "expense_positive", provenance="seeded", notes="B note"
    )

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(app, ["list-sign-conventions"])

    assert result.exit_code == 0
    output = result.output

    # Header columns present
    assert "account_id" in output
    assert "sign_convention" in output
    assert "provenance" in output
    assert "updated_at" in output
    assert "notes" in output

    # All three account IDs appear
    assert "a-acct" in output
    assert "b-acct" in output
    assert "z-acct" in output

    # Ordering: manual rows (a-acct, z-acct) come before seeded (b-acct)
    idx_manual_a = output.index("a-acct")
    idx_manual_z = output.index("z-acct")
    idx_seeded_b = output.index("b-acct")
    assert idx_manual_a < idx_seeded_b
    assert idx_manual_z < idx_seeded_b


def test_list_sign_conventions_notes_full(tmp_path: Path) -> None:
    """Notes are displayed in full without truncation."""
    db = create_db(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'list_sign_conv.db'}"

    long_note = "X" * 80
    db.set_sign_convention("acct-long", "expense_positive", notes=long_note)

    with patch.dict("os.environ", {"DATABASE_URL": db_url}):
        result = runner.invoke(app, ["list-sign-conventions"])

    assert result.exit_code == 0
    assert "X" * 80 in result.output
