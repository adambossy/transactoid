"""Smoke tests for AccountSignConvention ORM model and DB facade methods."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from penny.adapters.db.facade import DB
from penny.adapters.db.models import AccountSignConvention


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_set_and_get_sign_convention_golden_path(tmp_path: Path) -> None:
    # input
    account_id = "acct-1"
    convention = "expense_negative"

    # setup
    db = _create_db(tmp_path)

    # act
    db.set_sign_convention(account_id, convention)
    output = db.get_sign_convention(account_id)

    # expected
    expected_output = "expense_negative"

    # assert
    assert output == expected_output


def test_get_sign_convention_default_for_unknown_account(tmp_path: Path) -> None:
    # input
    account_id = "unknown-account"

    # setup
    db = _create_db(tmp_path)

    # act
    output = db.get_sign_convention(account_id)

    # expected
    expected_output = "expense_positive"

    # assert
    assert output == expected_output


def test_bulk_get_sign_conventions_mixed(tmp_path: Path) -> None:
    # input
    account_a = "a"
    account_b = "b"
    convention_a = "expense_negative"

    # setup
    db = _create_db(tmp_path)
    db.set_sign_convention(account_a, convention_a)

    # act
    output = db.bulk_get_sign_conventions([account_a, account_b])

    # expected
    expected_output = {
        "a": "expense_negative",
        "b": "expense_positive",
    }

    # assert
    assert output == expected_output


def test_set_sign_convention_upsert_updates_row(tmp_path: Path) -> None:
    # input
    account_id = "acct-upsert"

    # setup
    db = _create_db(tmp_path)
    db.set_sign_convention(account_id, "expense_positive")

    # act: second call should update, not raise
    db.set_sign_convention(account_id, "expense_negative", notes="updated")
    output = db.get_sign_convention(account_id)

    # expected
    expected_output = "expense_negative"

    # assert
    assert output == expected_output


def test_set_sign_convention_preserves_notes_when_omitted(tmp_path: Path) -> None:
    # input
    account_id = "acct-notes"
    original_notes = "seeded from Plaid survey"

    # setup
    db = _create_db(tmp_path)
    db.set_sign_convention(account_id, "expense_positive", notes=original_notes)

    # act: update convention without passing notes=
    db.set_sign_convention(account_id, "expense_negative")

    # expected: notes column unchanged
    expected_output = original_notes

    # assert
    with db.session() as session:
        row = session.get(AccountSignConvention, account_id)
        assert row is not None
        output = row.notes
    assert output == expected_output


def test_set_sign_convention_invalid_value_raises(tmp_path: Path) -> None:
    # input
    account_id = "acct-bad"

    # setup
    db = _create_db(tmp_path)

    # act + assert: CHECK constraint rejects invalid sign_convention via the facade
    with pytest.raises(IntegrityError):
        db.set_sign_convention(account_id, "nonsense")
