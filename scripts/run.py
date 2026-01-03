from __future__ import annotations

import os
from pathlib import Path

from transactoid.adapters.amazon import AmazonMutationPlugin, AmazonMutationPluginConfig
from transactoid.adapters.clients.plaid import PlaidClient
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.sync import MutationRegistry
from transactoid.tools.sync.sync_tool import SyncTool


def run_sync(
    *,
    access_token: str,
    cursor: str | None = None,
    count: int = 500,
) -> None:
    """
    Sync transactions from Plaid and categorize them using an LLM.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
    """
    # Initialize dependencies
    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)
    taxonomy = load_taxonomy_from_db(db)
    plaid_client = PlaidClient.from_env()
    categorizer = Categorizer(taxonomy)

    # Setup mutation registry with Amazon plugin if CSV dir exists
    mutation_registry = MutationRegistry()
    amazon_csv_dir = Path(".transactions/amazon")
    if amazon_csv_dir.exists():
        mutation_registry.register(
            AmazonMutationPlugin(AmazonMutationPluginConfig(csv_dir=amazon_csv_dir))
        )

    # Create and execute sync tool
    sync_tool = SyncTool(
        plaid_client=plaid_client,
        categorizer=categorizer,
        db=db,
        taxonomy=taxonomy,
        access_token=access_token,
        cursor=cursor,
        mutation_registry=mutation_registry,
    )

    results = sync_tool.sync(count=count)

    # Display results
    total_added = sum(r.added_count for r in results)
    total_modified = sum(r.modified_count for r in results)
    total_removed = sum(len(r.removed_transaction_ids) for r in results)

    print(f"Sync complete: {len(results)} batch(es)")
    print(f"  Added: {total_added}")
    print(f"  Modified: {total_modified}")
    print(f"  Removed: {total_removed}")


def run_pipeline(
    *,
    access_token: str,
    cursor: str | None = None,
    count: int = 500,
    questions: list[str] | None = None,
) -> None:
    """
    Run the full pipeline: sync → categorize → persist.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
        questions: Optional questions for analytics
    """
    return None
