from __future__ import annotations

import asyncio
import os

from transactoid.adapters.clients.plaid import PlaidClient
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.sync.sync_tool import SyncTool


async def _run_sync_async(
    *,
    count: int = 500,
) -> None:
    """
    Async implementation of sync logic.

    Args:
        count: Maximum number of transactions to fetch per request
    """
    # Initialize dependencies
    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)
    taxonomy = load_taxonomy_from_db(db)
    plaid_client = PlaidClient.from_env()
    # SyncTool handles all items, cursor persistence, and Amazon mutations
    sync_tool = SyncTool(
        plaid_client=plaid_client,
        categorizer_factory=lambda: Categorizer(taxonomy),
        db=db,
        taxonomy=taxonomy,
    )

    summary = await sync_tool.sync(count=count)

    # Display results
    print(f"Sync complete: {summary.items_synced} item(s)")
    print(f"  Added: {summary.total_added}")
    print(f"  Modified: {summary.total_modified}")
    print(f"  Removed: {summary.total_removed}")


def run_sync(
    *,
    count: int = 500,
) -> None:
    """
    Sync transactions from ALL Plaid items and categorize them using an LLM.

    SyncTool handles cursor persistence and Amazon mutation plugin automatically.

    Args:
        count: Maximum number of transactions to fetch per request
    """
    asyncio.run(_run_sync_async(count=count))


def run_pipeline(
    *,
    count: int = 500,
    questions: list[str] | None = None,
) -> None:
    """
    Run the full pipeline: sync → categorize → persist.

    Args:
        count: Maximum number of transactions to fetch per request
        questions: Optional questions for analytics
    """
    return None
