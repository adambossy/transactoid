"""MCP server exposing Transactoid tools via Anthropic MCP SDK."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from transactoid.adapters.clients.plaid import PlaidClient
from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.persist.persist_tool import PersistTool
from transactoid.tools.sync.sync_tool import SyncTool

# Load environment variables
load_dotenv(override=False)

# Initialize services globally
db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
db = DB(db_url)
taxonomy = load_taxonomy_from_db(db)
categorizer = Categorizer(taxonomy)
persist_tool = PersistTool(db, taxonomy)

# Create FastMCP server
mcp = FastMCP(name="transactoid")


@mcp.tool()
async def sync_transactions(count: int = 250) -> dict[str, Any]:
    """
    Trigger synchronization with Plaid to fetch latest transactions.

    Syncs ALL connected Plaid items, categorizes transactions, and persists
    to the database. Handles cursor persistence automatically for incremental
    syncs.

    Args:
        count: Maximum number of transactions to sync per page (default: 250)

    Returns:
        Dictionary with sync status and summary including items_synced,
        total_added, total_modified, and total_removed counts.
    """
    try:
        plaid_client = PlaidClient.from_env()

        sync_tool = SyncTool(
            plaid_client=plaid_client,
            categorizer=categorizer,
            db=db,
            taxonomy=taxonomy,
        )

        summary = await sync_tool.sync(count=count)
        return {"status": "success", **summary.to_dict()}
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "items_synced": 0,
            "total_added": 0,
            "total_modified": 0,
            "total_removed": 0,
        }


@mcp.tool()
def recategorize_merchant(merchant_id: int, category_key: str) -> dict[str, Any]:
    """
    Recategorize all transactions for a specific merchant.

    Args:
        merchant_id: The merchant ID to recategorize
        category_key: The new category key (e.g., "FOOD.GROCERIES")

    Returns:
        Dictionary with recategorization results
    """
    try:
        if not taxonomy.is_valid_key(category_key):
            return {
                "status": "error",
                "message": f"Invalid category key: {category_key}",
                "updated": 0,
            }

        updated_count = persist_tool.recategorize_merchant(
            merchant_id=merchant_id, category_key=category_key
        )

        return {
            "status": "success",
            "updated": updated_count,
            "message": (
                f"Recategorized {updated_count} transactions to {category_key}"
            ),
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "updated": 0}


@mcp.tool()
def tag_transactions(transaction_ids: list[int], tags: list[str]) -> dict[str, Any]:
    """
    Apply tags to specific transactions.

    Args:
        transaction_ids: List of transaction IDs to tag
        tags: List of tag names to apply

    Returns:
        Dictionary with tagging results
    """
    try:
        result = persist_tool.apply_tags(transaction_ids, tags)

        return {
            "status": "success",
            "applied": result.applied,
            "created_tags": result.created_tags,
            "message": f"Applied {len(tags)} tags to {result.applied} transactions",
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "applied": 0, "created_tags": []}


@mcp.tool()
def connect_new_account() -> dict[str, Any]:
    """
    Trigger UI flow for connecting a new bank/institution via Plaid.

    Opens a browser window for the user to link their bank account via Plaid
    Link. The function handles the full OAuth flow, exchanges the public token
    for an access token, and stores the connection in the database.

    Returns:
        Dictionary with connection status including:
        - status: "success" or "error"
        - item_id: Plaid item ID if successful
        - institution_name: Institution name if available
        - message: Human-readable status message
    """
    try:
        plaid_client = PlaidClient.from_env()
        return plaid_client.connect_new_account(db=db)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to connect account: {str(e)}",
        }


@mcp.tool()
def list_plaid_accounts() -> dict[str, Any]:
    """
    List all connected Plaid accounts.

    Returns:
        Dictionary with list of connected accounts including item_id,
        institution_id, institution_name, and access_token status.
    """
    try:
        plaid_items = db.list_plaid_items()

        if not plaid_items:
            return {
                "status": "success",
                "accounts": [],
                "message": "No Plaid accounts connected",
            }

        accounts = []
        for item in plaid_items:
            accounts.append(
                {
                    "item_id": item.item_id,
                    "institution_id": item.institution_id or "unknown",
                    "institution_name": item.institution_name or "Unknown Institution",
                    "has_access_token": bool(item.access_token),
                    "created_at": (
                        item.created_at.isoformat() if item.created_at else None
                    ),
                    "updated_at": (
                        item.updated_at.isoformat() if item.updated_at else None
                    ),
                }
            )

        return {
            "status": "success",
            "accounts": accounts,
            "count": len(accounts),
            "message": f"Found {len(accounts)} connected account(s)",
        }
    except Exception as e:
        return {
            "status": "error",
            "accounts": [],
            "count": 0,
            "message": f"Error listing accounts: {str(e)}",
        }


@mcp.tool()
def run_sql(query: str) -> dict[str, Any]:
    """
    Execute SQL queries against the transaction database.

    Args:
        query: SQL query string to execute

    Returns:
        Dictionary with 'rows' (list of dicts) and 'count' (number of rows)
    """
    try:
        result = db.execute_raw_sql(query)

        if result.returns_rows:
            # Convert Row objects to dicts
            rows = [dict(row._mapping) for row in result.fetchall()]
            # Convert date/datetime objects to strings for JSON serialization
            for row in rows:
                for key, value in row.items():
                    if hasattr(value, "isoformat"):
                        row[key] = value.isoformat()
            return {"status": "success", "rows": rows, "count": len(rows)}
        else:
            return {"status": "success", "rows": [], "count": result.rowcount}
    except Exception as e:
        return {"status": "error", "rows": [], "count": 0, "error": str(e)}


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
