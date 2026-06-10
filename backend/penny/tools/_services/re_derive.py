"""Re-derive unverified derived transactions for a given Plaid account.

Why this exists: after a sign-convention change (or any correction that
affects how plaid_transactions map to derived_transactions), the existing
unverified derived rows for an account are stale.  This module re-runs the
mutation -> categorize chain only over the unverified rows so the user gets
fresh derived data without touching anything they have manually verified.

Verified rows are completely preserved — this is a hard invariant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from penny.adapters.db.facade import DB


class SupportsReDerive(Protocol):
    """Subset of ``SyncTool`` the re-derive flow drives.

    A Protocol so tests can inject a stub without constructing a real SyncTool
    (which needs Plaid + OpenAI credentials).
    """

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]: ...

    async def _categorize_derived(self, derived_ids: list[int]) -> None: ...


@dataclass(frozen=True, slots=True)
class ReDeriveResult:
    """Structured outcome of a re-derive operation."""

    deleted_count: int
    new_derived_count: int
    categorized_count: int
    verified_skipped: int
    mutate_failed: bool
    categorize_failed: bool
    failure_message: str | None


def _default_sync_tool(db: DB) -> SupportsReDerive:
    """Build a real ``SyncTool`` wired to the given DB."""
    from penny.adapters.clients.plaid import PlaidClient
    from penny.services import build_categorizer, get_taxonomy
    from penny.tools._services.sync_service import SyncTool

    return SyncTool(
        plaid_client=PlaidClient.from_env(),
        categorizer_factory=build_categorizer,
        db=db,
        taxonomy=get_taxonomy(),
    )


def re_derive_account(
    db: DB,
    account_id: str,
    *,
    sync_tool_factory: Callable[[DB], SupportsReDerive] | None = None,
) -> ReDeriveResult:
    """Re-derive and re-categorize all unverified derived rows for an account.

    Steps:
    1. Verify the account has a sign convention configured (preflight guard).
    2. Resolve all plaid_transaction_ids belonging to the account.
    3. Count verified derived rows (to report; they are NOT touched).
    4. Delete unverified derived rows for those plaid_transaction_ids.
    5. Re-run ``_mutate_batch_to_derived`` over the full plaid_id list.
       (The method already guards verified rows internally, so passing all
       plaid_ids is safe — the guard here at the service layer is belt-and-
       suspenders.)
    6. Categorize the new unverified rows.

    Args:
        db: Database facade.
        account_id: Plaid account_id to re-derive.
        sync_tool_factory: Optional factory for the mutation/categorize runner.
            Defaults to a real ``SyncTool``.

    Returns:
        ReDeriveResult with counts and failure flags.

    Raises:
        ValueError: if account_id has no plaid_transactions, or if no sign
            convention is configured for the account.
    """
    plaid_ids = db.list_plaid_transaction_ids_for_account(account_id)
    if not plaid_ids:
        raise ValueError(f"no transactions found for account {account_id}")

    if not db.has_sign_convention(account_id):
        raise ValueError(
            f"no sign convention configured for account {account_id!r}; "
            f"call `set_sign_convention` first"
        )

    derived_map = db.get_derived_by_plaid_ids(plaid_ids)
    verified_skipped = sum(
        1 for rows in derived_map.values() for row in rows if row.is_verified
    )
    deleted_count = sum(
        1 for rows in derived_map.values() for row in rows if not row.is_verified
    )

    db.delete_unverified_derived_by_plaid_ids(plaid_ids)

    factory = sync_tool_factory or _default_sync_tool
    runner = factory(db)

    try:
        new_derived_ids = runner._mutate_batch_to_derived(plaid_ids)
    except Exception as exc:
        return ReDeriveResult(
            deleted_count=deleted_count,
            new_derived_count=0,
            categorized_count=0,
            verified_skipped=verified_skipped,
            mutate_failed=True,
            categorize_failed=False,
            failure_message=str(exc),
        )

    try:
        asyncio.run(runner._categorize_derived(new_derived_ids))
    except Exception as exc:
        return ReDeriveResult(
            deleted_count=deleted_count,
            new_derived_count=len(new_derived_ids),
            categorized_count=0,
            verified_skipped=verified_skipped,
            mutate_failed=False,
            categorize_failed=True,
            failure_message=str(exc),
        )

    return ReDeriveResult(
        deleted_count=deleted_count,
        new_derived_count=len(new_derived_ids),
        categorized_count=len(new_derived_ids),
        verified_skipped=verified_skipped,
        mutate_failed=False,
        categorize_failed=False,
        failure_message=None,
    )
