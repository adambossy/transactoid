"""MCP server exposing Transactoid tools via Anthropic MCP SDK."""

from __future__ import annotations

from datetime import date
import os
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from mcp.server.fastmcp import FastMCP

from transactoid.adapters.clients.plaid import PlaidClient
from transactoid.adapters.db.facade import DB
from transactoid.bootstrap import run_initialization_hooks
from transactoid.rules.loader import MerchantRulesLoader
from transactoid.services.re_derive import (
    ReDeriveResult,
    re_derive_account as _re_derive_account,
)
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.amazon.remutate import (
    remutate_amazon_orders as _remutate_amazon,
)
from transactoid.tools.amazon.scraper import (
    BackendType,
    scrape_amazon_orders as _scrape_amazon,
)
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.migrate.dispatcher import run_migration
from transactoid.tools.migrate.migration_tool import MigrationTool
from transactoid.tools.persist.persist_tool import PersistTool
from transactoid.tools.sync.sync_tool import SyncTool
from transactoid.workspace import resolve_memory_dir

# Load environment variables
load_dotenv(override=False)

# Initialize services globally
db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
db = DB(db_url)
taxonomy = load_taxonomy_from_db(db)
persist_tool = PersistTool(db, taxonomy)

# Initialize merchant rules loader
memory_dir = resolve_memory_dir()
init_result = run_initialization_hooks(memory_dir=memory_dir)
if init_result[2] is not None:
    logger.debug("Memory index initialization hook reported error")
merchant_rules_path = memory_dir / "merchant-rules.md"
rules_loader = MerchantRulesLoader(merchant_rules_path, taxonomy=taxonomy)

# MigrationTool needs a Categorizer for split's constrained-recategorization;
# merge no longer consults it (see migration_tool.merge_categories docstring).
_migration_categorizer = Categorizer(taxonomy, rules_loader=rules_loader)
migration_tool = MigrationTool(db, taxonomy, _migration_categorizer)

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
            categorizer_factory=lambda: Categorizer(
                taxonomy, rules_loader=rules_loader
            ),
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
def migrate_taxonomy(
    operation: str,
    source_key: str | None = None,
    target_key: str | None = None,
    source_keys: list[str] | None = None,
    targets: list[dict[str, str | None]] | None = None,
    new_key: str | None = None,
    name: str | None = None,
    parent_key: str | None = None,
    description: str | None = None,
    fallback_key: str | None = None,
) -> dict[str, Any]:
    """
    Perform a taxonomy migration: add, remove, rename, merge, or split.

    Required arguments per operation:
    - **add**: new_key, name; optional parent_key, description
    - **remove**: source_key; optional fallback_key (required if category has txns)
    - **rename**: source_key, new_key
    - **merge**: source_keys, target_key
    - **split**: source_key, targets (list of {key, name, description})

    Merge does not consult the LLM — it bulk-reassigns every source-category
    transaction to target_key and preserves is_verified (merging is itself a
    user-driven verification of the new bucket). Split uses constrained
    recategorization among the new targets.

    Returns a result dict with: success, operation, affected_transactions,
    recategorized, verified_retained, verified_demoted, errors, summary.
    """
    typed_targets: list[tuple[str, str, str | None]] | None = None
    if targets:
        typed_targets = []
        for target in targets:
            key = target.get("key")
            target_name = target.get("name")
            if not isinstance(key, str) or not isinstance(target_name, str):
                return {
                    "success": False,
                    "operation": operation,
                    "errors": ["each target requires string 'key' and 'name'"],
                    "summary": "Failed: malformed targets",
                }
            target_description = target.get("description")
            description_value = (
                target_description if isinstance(target_description, str) else None
            )
            typed_targets.append((key, target_name, description_value))

    return run_migration(
        migration_tool,
        operation=operation,
        source_key=source_key,
        target_key=target_key,
        source_keys=source_keys,
        targets=typed_targets,
        new_key=new_key,
        name=name,
        parent_key=parent_key,
        description=description,
        fallback_key=fallback_key,
    )


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


@mcp.tool()
def scrape_amazon_orders(
    since: str | None = None,
    until: str | None = None,
    max_orders: int = 10,
    backend: str = "stagehand-browserbase",
    profile_key: str | None = None,
) -> dict[str, Any]:
    """
    Scrape Amazon order history for all enabled Amazon login profiles.

    Runs a two-phase workflow: first authenticates each enabled profile
    sequentially (creating Browserbase contexts on first use), then scrapes
    order history for each ready profile.

    The orchestrator floors ``since`` at the earliest plaid_transactions
    posted_at date in the DB; orders predating any real charge are skipped.

    Args:
        since: Inclusive lower bound on order date as ISO ``YYYY-MM-DD``.
        until: Inclusive upper bound on order date as ISO ``YYYY-MM-DD``.
        max_orders: Maximum number of orders to scrape per profile (default: 10)
        backend: Backend to use - "stagehand" (local browser),
            "stagehand-browserbase" (cloud with session persistence), or
            "playwriter".
        profile_key: If set, scrape only the profile with this key (must be
            enabled). When omitted, scrape all enabled profiles.

    Returns:
        Dictionary with top-level status, aggregate counts, and per-profile
        breakdown.
    """
    try:
        if backend not in ("stagehand", "stagehand-browserbase", "playwriter"):
            return {
                "status": "error",
                "message": f"Invalid backend: {backend}",
                "orders_created": 0,
                "items_created": 0,
                "profiles_total": 0,
                "profiles_ready": 0,
                "profiles_succeeded": 0,
                "profiles_failed": 0,
                "profile_results": [],
            }
        try:
            since_date = date.fromisoformat(since) if since is not None else None
            until_date = date.fromisoformat(until) if until is not None else None
        except ValueError as e:
            return {
                "status": "error",
                "message": f"Invalid date format (expected YYYY-MM-DD): {e}",
                "orders_created": 0,
                "items_created": 0,
                "profiles_total": 0,
                "profiles_ready": 0,
                "profiles_succeeded": 0,
                "profiles_failed": 0,
                "profile_results": [],
            }
        # Cast is safe after validation above
        validated_backend: BackendType = backend  # type: ignore[assignment]
        return _scrape_amazon(
            db,
            backend=validated_backend,
            since=since_date,
            until=until_date,
            max_orders=max_orders,
            profile_key=profile_key,
        )
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "orders_created": 0,
            "items_created": 0,
            "profiles_total": 0,
            "profiles_ready": 0,
            "profiles_succeeded": 0,
            "profiles_failed": 0,
            "profile_results": [],
        }


@mcp.tool()
def remutate_amazon_orders(dry_run: bool = True) -> dict[str, Any]:
    """
    Re-split pre-existing Plaid txns that now match scraped Amazon orders.

    The sync mutation phase only sees newly-fetched Plaid txns, so a charge
    that posted before an Amazon scrape never gets split. This re-runs the
    match -> split -> categorize chain over a bounded window of already
    persisted Plaid transactions.

    Destructive: matched Plaid txns have their existing derived rows deleted
    and replaced by per-item splits. ``dry_run`` defaults to True; the
    returned ``overwrite_details`` lists any manually-categorized or verified
    rows that an apply (``dry_run=False``) would replace. Inspect a dry run
    before applying.

    Args:
        dry_run: When True (default), compute and return scope without
            writing. Pass False to apply the splits.

    Returns:
        Result dict: status, candidates, matched, overwrites,
        overwrite_details, derived_after_split, categorized, dry_run, message.
    """
    try:
        return _remutate_amazon(db, dry_run=dry_run)
    except Exception as e:
        return {
            "status": "error",
            "candidates": 0,
            "matched": 0,
            "overwrites": 0,
            "overwrite_details": [],
            "derived_after_split": 0,
            "categorized": 0,
            "dry_run": dry_run,
            "message": str(e),
        }


@mcp.tool()
async def generate_chart(
    chart_type: str,
    title: str,
    data: dict[str, float],
    x_label: str = "",
    y_label: str = "",
) -> dict[str, Any]:
    """Generate a chart and return base64 PNG, file path, and optional ASCII plot.

    Args:
        chart_type: Type of chart — "bar", "line", or "pie"
        title: Chart title
        data: Label-to-number mapping, e.g. {"Groceries": 450.0}
        x_label: Optional x-axis label
        y_label: Optional y-axis label

    Returns:
        Dictionary with html_img_tag, file_path, title, and ascii_plot.
    """
    from transactoid.tools.visualize.chart_tool import GenerateChartTool

    tool = GenerateChartTool()
    return await tool.execute(
        chart_type=chart_type,
        title=title,
        data=data,
        x_label=x_label,
        y_label=y_label,
    )


@mcp.tool()
def list_amazon_logins() -> dict[str, Any]:
    """List all configured Amazon login profiles."""
    profiles = db.list_amazon_login_profiles()
    return {
        "profiles": [
            {
                "profile_key": p.profile_key,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "sort_order": p.sort_order,
                "has_context": p.browserbase_context_id is not None,
                "last_auth_status": p.last_auth_status,
                "last_auth_at": p.last_auth_at.isoformat() if p.last_auth_at else None,
            }
            for p in profiles
        ]
    }


@mcp.tool()
def add_amazon_login(
    profile_key: str,
    display_name: str,
    enabled: bool = True,
    sort_order: int = 0,
) -> dict[str, Any]:
    """Add a new Amazon login profile."""
    try:
        profile = db.create_amazon_login_profile(
            profile_key=profile_key,
            display_name=display_name,
            enabled=enabled,
            sort_order=sort_order,
        )
        return {
            "status": "success",
            "profile_key": profile.profile_key,
            "display_name": profile.display_name,
            "message": f"Created profile '{profile_key}'",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def update_amazon_login(
    profile_key: str,
    display_name: str | None = None,
    enabled: bool | None = None,
    sort_order: int | None = None,
) -> dict[str, Any]:
    """Update an existing Amazon login profile. At least one field must be provided."""
    if display_name is None and enabled is None and sort_order is None:
        return {
            "status": "error",
            "message": (
                "At least one of display_name, enabled, sort_order must be provided"
            ),
        }
    try:
        profile = db.update_amazon_login_profile(
            profile_key=profile_key,
            display_name=display_name,
            enabled=enabled,
            sort_order=sort_order,
        )
        return {
            "status": "success",
            "profile_key": profile.profile_key,
            "message": f"Updated profile '{profile_key}'",
        }
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def remove_amazon_login(profile_key: str) -> dict[str, Any]:
    """Remove an Amazon login profile."""
    try:
        db.delete_amazon_login_profile(profile_key=profile_key)
        return {"status": "success", "message": f"Removed profile '{profile_key}'"}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def clear_amazon_login_context(profile_key: str) -> dict[str, Any]:
    """Clear the stored Browserbase context ID for an Amazon login profile.

    Forces re-login on next scrape.
    """
    try:
        db.set_amazon_login_context_id(profile_key=profile_key, context_id=None)
        return {
            "status": "success",
            "message": f"Cleared context for profile '{profile_key}'",
        }
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def enable_amazon_login(profile_key: str) -> dict[str, Any]:
    """Enable an Amazon login profile."""
    try:
        db.update_amazon_login_profile(profile_key=profile_key, enabled=True)
        return {"status": "success", "message": f"Enabled profile '{profile_key}'"}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def disable_amazon_login(profile_key: str) -> dict[str, Any]:
    """Disable an Amazon login profile."""
    try:
        db.update_amazon_login_profile(profile_key=profile_key, enabled=False)
        return {"status": "success", "message": f"Disabled profile '{profile_key}'"}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


_MCP_VALID_SIGN_CONVENTIONS = frozenset({"expense_positive", "expense_negative"})


@mcp.tool()
def set_sign_convention(
    account_id: str,
    convention: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Set the sign convention for a Plaid account.

    Records whether the account reports expenses as positive amounts
    ('expense_positive') or negative amounts ('expense_negative').
    The provenance is always 'manual' for MCP/CLI invocations.

    Args:
        account_id: The Plaid account_id to configure.
        convention: 'expense_positive' or 'expense_negative'.
        notes: Optional free-text note (e.g., institution name).

    Returns:
        Dict with status and message.
    """
    if convention not in _MCP_VALID_SIGN_CONVENTIONS:
        return {
            "status": "error",
            "message": (
                f"convention must be 'expense_positive' or 'expense_negative'; "
                f"got {convention!r}"
            ),
        }
    try:
        db.set_sign_convention(account_id, convention, provenance="manual", notes=notes)
        return {
            "status": "success",
            "message": f"Set account {account_id} -> {convention}",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def list_sign_conventions() -> dict[str, Any]:
    """List all configured account sign conventions.

    Returns all rows from account_sign_conventions ordered by
    (provenance, account_id).

    Returns:
        Dict with 'conventions' list (each has account_id, sign_convention,
        provenance, updated_at, notes) and 'count'.
    """
    try:
        rows = db.list_sign_conventions()
        conventions = [
            {
                "account_id": row.account_id,
                "sign_convention": row.sign_convention,
                "provenance": row.provenance,
                "updated_at": row.updated_at.isoformat(),
                "notes": row.notes,
            }
            for row in rows
        ]
        return {
            "status": "success",
            "conventions": conventions,
            "count": len(conventions),
        }
    except Exception as exc:
        return {"status": "error", "conventions": [], "count": 0, "message": str(exc)}


@mcp.tool()
def re_derive(account_id: str) -> dict[str, Any]:
    """Re-derive and re-categorize all unverified derived rows for an account.

    Deletes unverified derived_transactions for the account's plaid_transactions,
    re-runs the mutation phase, then immediately categorizes the new rows.
    Verified rows are completely preserved.

    Args:
        account_id: Plaid account_id to re-derive.

    Returns:
        Dict with re_derived, verified_skipped, account_id, and message on
        success; status='error' and message on failure.
    """
    try:
        result: ReDeriveResult = _re_derive_account(db, account_id)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if result.mutate_failed:
        return {
            "status": "error",
            "message": (
                f"Re-derive incomplete: unverified rows were deleted but "
                f"re-derivation failed ({result.failure_message}). "
                f"Re-run re_derive for account {account_id} to retry."
            ),
        }

    if result.categorize_failed:
        return {
            "status": "error",
            "message": (
                f"Re-derived {result.new_derived_count} rows but categorization "
                f"failed ({result.failure_message}). "
                f"Run categorize to assign categories."
            ),
        }

    return {
        "status": "success",
        "account_id": account_id,
        "re_derived": result.new_derived_count,
        "verified_skipped": result.verified_skipped,
        "message": (
            f"Re-derived {result.new_derived_count} rows for account {account_id}. "
            f"{result.verified_skipped} verified rows preserved."
        ),
    }


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
