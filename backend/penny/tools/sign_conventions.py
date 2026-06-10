"""Agent tools for managing account sign conventions and re-deriving transactions."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.db import get_db

_VALID_CONVENTIONS = frozenset({"expense_positive", "expense_negative"})


@tool
async def set_sign_convention(
    account_id: str,
    convention: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Set the sign convention for a Plaid account.

    Controls how raw Plaid amount_cents are interpreted when deriving
    transactions. Most institutions use 'expense_positive' (Plaid default).
    Some institutions (e.g. BofA, Alliant) use 'expense_negative' where
    expenses arrive as negative amounts.

    Low-risk but persistent: changing the convention affects all future syncs
    and should be followed by ``re_derive_account`` to normalize historical rows.

    Args:
        account_id: Plaid account_id to configure.
        convention: Either 'expense_positive' or 'expense_negative'.
        notes: Optional free-text note (e.g. institution name or reason).
    """

    def _run() -> dict[str, Any]:
        if convention not in _VALID_CONVENTIONS:
            return {
                "status": "error",
                "message": (
                    f"Invalid convention {convention!r}. "
                    f"Must be one of: expense_positive, expense_negative"
                ),
            }

        get_db().set_sign_convention(
            account_id,
            convention,
            provenance="manual",
            notes=notes,
        )
        return {
            "status": "success",
            "message": f"Set account {account_id} -> {convention}",
        }

    return await asyncio.to_thread(_run)


@tool
async def list_sign_conventions() -> dict[str, Any]:
    """List all configured account sign conventions.

    Returns structured data for all rows in account_sign_conventions, ordered
    by (provenance, account_id). The agent renders this for the user.

    Returns:
        ``{"status": "success", "conventions": [...], "count": N}`` where each
        convention dict has keys: account_id, sign_convention, provenance,
        updated_at, notes.
    """

    def _run() -> dict[str, Any]:
        rows = get_db().list_sign_conventions()
        conventions = [
            {
                "account_id": row.account_id,
                "sign_convention": row.sign_convention,
                "provenance": row.provenance,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "notes": row.notes,
            }
            for row in rows
        ]
        return {
            "status": "success",
            "conventions": conventions,
            "count": len(conventions),
        }

    return await asyncio.to_thread(_run)


@tool
async def re_derive_account(account_id: str) -> dict[str, Any]:
    """Re-derive and re-categorize all unverified transactions for an account.

    DESTRUCTIVE: deletes all unverified derived_transactions for the account
    then re-runs the mutation and categorization pipeline to rebuild them.
    Verified rows are never touched.

    Use this after changing an account's sign convention to normalize
    historical rows. Confirm with the user first, showing the account and
    the count of unverified rows that will be replaced.

    Args:
        account_id: Plaid account_id whose unverified rows will be rebuilt.
    """

    def _run() -> dict[str, Any]:
        from penny.tools._services.re_derive import (
            re_derive_account as _re_derive_svc,
        )

        try:
            result = _re_derive_svc(get_db(), account_id)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        response: dict[str, Any] = {
            "status": "success",
            "account_id": account_id,
            "deleted": result.deleted_count,
            "re_derived": result.new_derived_count,
            "categorized": result.categorized_count,
            "verified_skipped": result.verified_skipped,
        }

        if result.mutate_failed or result.categorize_failed:
            response["status"] = "partial_failure"
            failed_stage = "mutate" if result.mutate_failed else "categorize"
            response["failed_stage"] = failed_stage
            response["failure_message"] = result.failure_message
            response["recovery"] = (
                f"The {failed_stage} step failed. Inspect the account and call "
                "`re_derive_account` again after resolving the issue."
            )

        return response

    return await asyncio.to_thread(_run)
