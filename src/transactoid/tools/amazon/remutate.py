"""Re-mutate pre-existing Plaid transactions through the Amazon split plugin.

Why this exists: the sync pipeline's mutation phase only sees Plaid txns that
were upserted in the *current* sync run. A Plaid charge that posted before a
later Amazon scrape is never re-presented to the mutation phase, so it stays
in ``derived_transactions`` as a 1:1 passthrough even though scraped order/item
data now exists for it. This module re-runs the match → split → categorize
chain over a bounded window of already-persisted Plaid txns to close that gap
(historical backfill, scrape-gap recovery, late Amazon finalization).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from transactoid.adapters.amazon import (
    AmazonMutationPlugin,
    AmazonMutationPluginConfig,
)

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB


class SupportsRemutation(Protocol):
    """Subset of ``SyncTool`` the remutation flow drives.

    Declared as a Protocol so tests can inject a fake without constructing a
    real ``SyncTool`` (which needs Plaid + OpenAI credentials).
    """

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]: ...

    async def _categorize_derived(self, derived_ids: list[int]) -> None: ...


def _default_sync_tool(db: DB) -> SupportsRemutation:
    """Build a real ``SyncTool`` (registers the Amazon mutation plugin)."""
    from transactoid.adapters.clients.plaid import PlaidClient
    from transactoid.taxonomy.loader import load_taxonomy_from_db
    from transactoid.tools.categorize.categorizer_tool import Categorizer
    from transactoid.tools.sync.sync_tool import SyncTool

    taxonomy = load_taxonomy_from_db(db)
    return SyncTool(
        plaid_client=PlaidClient.from_env(),
        categorizer_factory=lambda: Categorizer(taxonomy),
        db=db,
        taxonomy=taxonomy,
    )


def _result(
    *,
    status: str,
    message: str,
    candidates: int = 0,
    matched: int = 0,
    overwrites: int = 0,
    overwrite_details: list[dict[str, Any]] | None = None,
    derived_after_split: int = 0,
    categorized: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build the remutation result contract (flat dict, mirrors scraper)."""
    return {
        "status": status,
        "candidates": candidates,
        "matched": matched,
        "overwrites": overwrites,
        "overwrite_details": overwrite_details or [],
        "derived_after_split": derived_after_split,
        "categorized": categorized,
        "dry_run": dry_run,
        "message": message,
    }


def remutate_amazon_orders(
    db: DB,
    *,
    dry_run: bool = False,
    sync_tool_factory: Callable[[DB], SupportsRemutation] | None = None,
) -> dict[str, Any]:
    """Re-split pre-existing Plaid txns that now match scraped Amazon orders.

    Args:
        db: Database facade.
        dry_run: When True, compute candidate/match/overwrite counts and return
            without writing anything.
        sync_tool_factory: Optional factory producing the object that performs
            mutation + categorization. Defaults to a real ``SyncTool``. Only
            invoked on a non-dry run with at least one match.

    Returns:
        Result-contract dict with status, counts, and overwrite details.
    """
    bounds = db.amazon_order_date_bounds()
    if bounds is None:
        return _result(
            status="noop",
            message="No scraped Amazon orders; nothing to remutate.",
            dry_run=dry_run,
        )

    lo, hi = bounds
    # Window upper bound mirrors the matcher's max_date_lag: a charge can post
    # up to N days after the order_date.
    config = AmazonMutationPluginConfig()
    window_end = hi + timedelta(days=config.max_date_lag)

    plaid_txns = db.list_plaid_transactions_in_date_range(start=lo, end=window_end)
    if not plaid_txns:
        return _result(
            status="noop",
            message=f"No Plaid transactions in [{lo}, {window_end}].",
            dry_run=dry_run,
        )

    # The plugin filters to Amazon-descriptor txns internally and matches them
    # to scraped orders by amount + date lag.
    plugin = AmazonMutationPlugin(db, config)
    plugin.initialize(plaid_txns)
    matched_plaid_ids = sorted(
        t.plaid_transaction_id for t in plaid_txns if plugin.should_handle(t)
    )

    candidates = len(plaid_txns)
    matched = len(matched_plaid_ids)
    if not matched_plaid_ids:
        return _result(
            status="noop",
            message=f"{candidates} Plaid txns in window; none matched an order.",
            candidates=candidates,
            dry_run=dry_run,
        )

    derived_map = db.get_derived_by_plaid_ids(matched_plaid_ids)
    overwrite_details: list[dict[str, Any]] = []
    for plaid_id, drvs in derived_map.items():
        for drv in drvs:
            if drv.is_verified or drv.category_method == "manual":
                overwrite_details.append(
                    {
                        "plaid_transaction_id": plaid_id,
                        "derived_transaction_id": drv.transaction_id,
                        "posted_at": drv.posted_at.isoformat(),
                        "amount_cents": drv.amount_cents,
                        "is_verified": drv.is_verified,
                        "category_method": drv.category_method,
                        "category_id": drv.category_id,
                        "merchant_descriptor": drv.merchant_descriptor,
                    }
                )
    overwrites = len(overwrite_details)
    if overwrites:
        logger.warning(
            "{} manually-categorized/verified derived row(s) will be deleted "
            "and replaced by Amazon splits",
            overwrites,
        )

    if dry_run:
        return _result(
            status="dry_run",
            message=(
                f"Dry run: {matched} of {candidates} Plaid txns would be split; "
                f"{overwrites} manual/verified row(s) would be replaced."
            ),
            candidates=candidates,
            matched=matched,
            overwrites=overwrites,
            overwrite_details=overwrite_details,
            dry_run=True,
        )

    factory = sync_tool_factory or _default_sync_tool
    runner = factory(db)

    logger.info("Re-mutating {} Plaid txns", matched)
    new_derived_ids = runner._mutate_batch_to_derived(matched_plaid_ids)
    # Mirror the sync flow, which categorizes immediately after mutation. The
    # plugin sets category_id=None on freshly split rows; without this they
    # would persist uncategorized.
    asyncio.run(runner._categorize_derived(new_derived_ids))

    return _result(
        status="ok",
        message=(
            f"Split {matched} Plaid txns into {len(new_derived_ids)} derived "
            f"rows and categorized them; {overwrites} manual/verified row(s) "
            "replaced."
        ),
        candidates=candidates,
        matched=matched,
        overwrites=overwrites,
        overwrite_details=overwrite_details,
        derived_after_split=len(new_derived_ids),
        categorized=len(new_derived_ids),
    )
