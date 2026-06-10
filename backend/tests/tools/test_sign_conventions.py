"""Light tool-shape tests for sign convention agent tools.

Verifies success and error dict shapes. The @tool decorator wraps functions
in a Tool dataclass; call .fn() directly to bypass the harness.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from penny.tools.sign_conventions import (
    list_sign_conventions,
    re_derive_account,
    set_sign_convention,
)

# ---------------------------------------------------------------------------
# set_sign_convention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_sign_convention_success_shape(isolated_db: None) -> None:
    """Success response includes status and confirmation message."""
    from penny.db import get_db

    get_db().create_schema()

    result = await set_sign_convention.fn(
        account_id="acct-x", convention="expense_negative"
    )

    assert result["status"] == "success"
    assert "acct-x" in result["message"]
    assert "expense_negative" in result["message"]


@pytest.mark.asyncio
async def test_set_sign_convention_invalid_convention_shape() -> None:
    """Invalid convention returns error with valid values listed."""
    result = await set_sign_convention.fn(account_id="acct-x", convention="bad_value")

    assert result["status"] == "error"
    assert "expense_positive" in result["message"]
    assert "expense_negative" in result["message"]


@pytest.mark.asyncio
async def test_set_sign_convention_with_notes_persisted(isolated_db: None) -> None:
    """Notes are stored and retrievable after the call."""
    from penny.db import get_db

    get_db().create_schema()

    await set_sign_convention.fn(
        account_id="acct-notes",
        convention="expense_positive",
        notes="Chase savings account",
    )

    rows = get_db().list_sign_conventions()
    matching = [r for r in rows if r.account_id == "acct-notes"]
    assert len(matching) == 1
    assert matching[0].notes == "Chase savings account"


# ---------------------------------------------------------------------------
# list_sign_conventions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sign_conventions_empty_shape(isolated_db: None) -> None:
    """Empty DB returns success with empty list."""
    from penny.db import get_db

    get_db().create_schema()

    result = await list_sign_conventions.fn()

    assert result == {"status": "success", "conventions": [], "count": 0}


@pytest.mark.asyncio
async def test_list_sign_conventions_with_rows_shape(isolated_db: None) -> None:
    """Rows are returned as dicts with the expected keys."""
    from penny.db import get_db

    get_db().create_schema()
    get_db().set_sign_convention("acct-a", "expense_positive", provenance="manual")
    get_db().set_sign_convention("acct-b", "expense_negative", provenance="seeded")

    result = await list_sign_conventions.fn()

    assert result["status"] == "success"
    assert result["count"] == 2

    # Each dict has exactly the expected keys
    keys_in_each = {frozenset(c.keys()) for c in result["conventions"]}
    expected_keys = frozenset(
        {"account_id", "sign_convention", "provenance", "updated_at", "notes"}
    )
    assert keys_in_each == {expected_keys}

    account_ids = {c["account_id"] for c in result["conventions"]}
    assert account_ids == {"acct-a", "acct-b"}


# ---------------------------------------------------------------------------
# re_derive_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_derive_account_error_shape_on_value_error(
    isolated_db: None,
) -> None:
    """ValueError from service is surfaced as status=error."""
    from penny.db import get_db

    get_db().create_schema()

    with patch(
        "penny.tools._services.re_derive.re_derive_account",
        side_effect=ValueError("no transactions found for account no-such-account"),
    ):
        result = await re_derive_account.fn(account_id="no-such-account")

    assert result["status"] == "error"
    assert "no-such-account" in result["message"]


@pytest.mark.asyncio
async def test_re_derive_account_success_shape(isolated_db: None) -> None:
    """Successful re-derive returns counts and success status."""
    from penny.db import get_db
    from penny.tools._services.re_derive import ReDeriveResult

    get_db().create_schema()

    success_result = ReDeriveResult(
        deleted_count=2,
        new_derived_count=2,
        categorized_count=2,
        verified_skipped=0,
        mutate_failed=False,
        categorize_failed=False,
        failure_message=None,
    )

    with patch(
        "penny.tools._services.re_derive.re_derive_account",
        return_value=success_result,
    ):
        result = await re_derive_account.fn(account_id="acct-rd")

    assert result["status"] == "success"
    assert result["account_id"] == "acct-rd"
    assert result["deleted"] == 2
    assert result["re_derived"] == 2
    assert result["categorized"] == 2
    assert result["verified_skipped"] == 0
    assert "failed_stage" not in result


@pytest.mark.asyncio
async def test_re_derive_account_partial_failure_shape(isolated_db: None) -> None:
    """Mutate failure surfaces as partial_failure with recovery guidance."""
    from penny.db import get_db
    from penny.tools._services.re_derive import ReDeriveResult

    get_db().create_schema()

    failure_result = ReDeriveResult(
        deleted_count=3,
        new_derived_count=0,
        categorized_count=0,
        verified_skipped=1,
        mutate_failed=True,
        categorize_failed=False,
        failure_message="DB connection lost",
    )

    with patch(
        "penny.tools._services.re_derive.re_derive_account",
        return_value=failure_result,
    ):
        result = await re_derive_account.fn(account_id="acct-partial")

    assert result["status"] == "partial_failure"
    assert result["failed_stage"] == "mutate"
    assert result["failure_message"] == "DB connection lost"
    assert "recovery" in result
    assert result["deleted"] == 3
    assert result["verified_skipped"] == 1
