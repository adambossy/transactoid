"""Tests for DB.seed_sign_conventions_from_institutions facade method."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import AccountSignConvention


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    account_id: str,
    institution: str | None,
    external_id: str,
) -> None:
    """Insert a minimal PlaidTransaction with the given account_id and institution."""
    db.upsert_plaid_transaction(
        external_id=external_id,
        source="PLAID",
        account_id=account_id,
        posted_at=date(2026, 1, 1),
        amount_cents=100,
        currency="USD",
        merchant_descriptor="Test",
        institution=institution,
    )


def _get_convention_row(db: DB, account_id: str) -> AccountSignConvention | None:
    """Return the AccountSignConvention row for account_id, or None."""
    with db.session() as session:
        row = session.get(AccountSignConvention, account_id)
        if row is not None:
            session.expunge(row)
        return row


def _as_convention_dict(row: AccountSignConvention | None) -> dict[str, str | None]:
    """Convert an AccountSignConvention row to a comparable dict."""
    if row is None:
        return {}
    return {
        "sign_convention": row.sign_convention,
        "provenance": row.provenance,
    }


def test_seed_sign_conventions_golden_path(tmp_path: Path) -> None:
    # input
    mapping = {
        "Chase": "expense_positive",
        "Bank of America": "expense_negative",
    }

    # setup: 3 accounts at 2 known institutions + 1 unknown
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-chase", institution="Chase", external_id="e1"
    )
    _insert_plaid_txn(
        db, account_id="acct-boa", institution="Bank of America", external_id="e2"
    )
    _insert_plaid_txn(
        db,
        account_id="acct-amex",
        institution="American Express",
        external_id="e3",
    )

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected
    expected_output = {"inserted": 3, "skipped_existing": 0, "default_applied": 1}

    # assert
    assert output == expected_output


def test_seed_sign_conventions_known_institution_row_fields(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive", "Bank of America": "expense_negative"}

    # setup
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-chase", institution="Chase", external_id="e1"
    )
    _insert_plaid_txn(
        db, account_id="acct-boa", institution="Bank of America", external_id="e2"
    )
    db.seed_sign_conventions_from_institutions(mapping)

    # act
    chase_row = _get_convention_row(db, "acct-chase")
    boa_row = _get_convention_row(db, "acct-boa")
    output = {
        "chase": _as_convention_dict(chase_row),
        "boa": _as_convention_dict(boa_row),
    }

    # expected
    expected_output = {
        "chase": {"sign_convention": "expense_positive", "provenance": "seeded"},
        "boa": {"sign_convention": "expense_negative", "provenance": "seeded"},
    }

    # assert
    assert output == expected_output


def test_seed_sign_conventions_unknown_institution_row_fields(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup: account at institution not in mapping (default applied)
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-amex", institution="American Express", external_id="e1"
    )
    db.seed_sign_conventions_from_institutions(mapping)

    # act
    output = _as_convention_dict(_get_convention_row(db, "acct-amex"))

    # expected: falls back to expense_positive with seeded provenance
    expected_output = {"sign_convention": "expense_positive", "provenance": "seeded"}

    # assert
    assert output == expected_output


def test_seed_sign_conventions_default_for_unknown_institution(tmp_path: Path) -> None:
    # input
    mapping: dict[str, str] = {"Chase": "expense_positive"}

    # setup: account at an institution not in the mapping
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-random", institution="Random Bank", external_id="e1"
    )

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected
    expected_output = {"inserted": 1, "skipped_existing": 0, "default_applied": 1}

    # assert
    assert output == expected_output

    row = _get_convention_row(db, "acct-random")
    assert row is not None
    assert row.sign_convention == "expense_positive"
    assert row.provenance == "seeded"


def test_seed_sign_conventions_preserves_manual_override(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup: pre-insert a manual override for one account
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-manual", institution="Chase", external_id="e1"
    )
    _insert_plaid_txn(db, account_id="acct-new", institution="Chase", external_id="e2")
    db.set_sign_convention(
        "acct-manual", "expense_negative", provenance="manual", notes="override"
    )

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected: manual row skipped, new row inserted
    expected_output = {"inserted": 1, "skipped_existing": 1, "default_applied": 0}

    # assert
    assert output == expected_output

    manual_row = _get_convention_row(db, "acct-manual")
    assert manual_row is not None
    assert manual_row.sign_convention == "expense_negative"
    assert manual_row.provenance == "manual"
    assert manual_row.notes == "override"


def test_seed_sign_conventions_idempotent_on_rerun(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup
    db = _create_db(tmp_path)
    _insert_plaid_txn(db, account_id="acct-1", institution="Chase", external_id="e1")

    # act: run seeding twice
    first = db.seed_sign_conventions_from_institutions(mapping)
    second = db.seed_sign_conventions_from_institutions(mapping)

    # expected: second run inserts nothing
    expected_first = {"inserted": 1, "skipped_existing": 0, "default_applied": 0}
    expected_second = {"inserted": 0, "skipped_existing": 1, "default_applied": 0}

    # assert
    assert first == expected_first
    assert second == expected_second


def test_seed_sign_conventions_null_institution_uses_default(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup: CSV-sourced row with NULL institution
    db = _create_db(tmp_path)
    _insert_plaid_txn(db, account_id="acct-csv", institution=None, external_id="e1")

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected
    expected_output = {"inserted": 1, "skipped_existing": 0, "default_applied": 1}

    # assert
    assert output == expected_output


def test_seed_sign_conventions_null_institution_row_fields(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup: CSV-sourced row with NULL institution
    db = _create_db(tmp_path)
    _insert_plaid_txn(db, account_id="acct-csv", institution=None, external_id="e1")
    db.seed_sign_conventions_from_institutions(mapping)

    # act
    row = _get_convention_row(db, "acct-csv")
    assert row is not None
    output = {
        "sign_convention": row.sign_convention,
        "provenance": row.provenance,
        "notes": row.notes,
    }

    # expected
    expected_output = {
        "sign_convention": "expense_positive",
        "provenance": "seeded",
        "notes": "Seeded from institution=None",
    }

    # assert
    assert output == expected_output


def test_seed_sign_conventions_empty_table_returns_zeros(tmp_path: Path) -> None:
    # input
    mapping = {"Chase": "expense_positive"}

    # setup: no plaid_transactions at all
    db = _create_db(tmp_path)

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected
    expected_output = {"inserted": 0, "skipped_existing": 0, "default_applied": 0}

    # assert
    assert output == expected_output


def test_seed_sign_conventions_skips_existing_unknown_institution(
    tmp_path: Path,
) -> None:
    # Regression: default_applied must not increment for rows that are skipped
    # because they already have a convention in account_sign_conventions.

    # input: mapping has no entry for "Random Bank"
    mapping: dict[str, str] = {"Chase": "expense_positive"}

    # setup: pre-insert a manual override for an account at an unknown institution
    db = _create_db(tmp_path)
    _insert_plaid_txn(
        db, account_id="acct-manual", institution="Random Bank", external_id="e1"
    )
    db.set_sign_convention(
        "acct-manual", "expense_negative", provenance="manual", notes="override"
    )

    # act
    output = db.seed_sign_conventions_from_institutions(mapping)

    # expected: row was skipped (already exists), default_applied stays 0
    expected_output = {"inserted": 0, "skipped_existing": 1, "default_applied": 0}

    # assert
    assert output == expected_output
