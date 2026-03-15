from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from html import escape
import os
from pathlib import Path
import shlex
import shutil
from typing import Any, cast

from dotenv import load_dotenv
import typer
import yaml

from transactoid.adapters.db.facade import DB
from transactoid.services.scheduled_reports import (
    NEW_YORK_TZ,
    select_prompt_key,
)

# Load environment variables from .env
load_dotenv()

app = typer.Typer(
    help="Transactoid — personal finance agent CLI.",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _ensure_toad_installed() -> str:
    """Ensure Toad is installed, installing it if necessary. Returns toad path."""
    import subprocess

    toad_path = shutil.which("toad")
    if toad_path:
        return toad_path

    typer.echo("Installing Toad ACP client...")
    result = subprocess.run(  # noqa: S603
        ["uv", "tool", "install", "-U", "batrachian-toad", "--python", "3.12"],  # noqa: S607
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        typer.echo(f"Failed to install Toad: {result.stderr}", err=True)
        raise typer.Exit(1)

    typer.echo("Toad installed successfully.\n")

    # Check again after install
    toad_path = shutil.which("toad")
    if not toad_path:
        typer.echo(
            "Toad was installed but not found in PATH. "
            "You may need to restart your shell.",
            err=True,
        )
        raise typer.Exit(1)

    return toad_path


def _launch_toad() -> None:
    """Launch Toad ACP client connected to Transactoid."""
    toad_path = _ensure_toad_installed()

    log_dir = Path(".logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "transactoid.log"

    cmd = f"uv run transactoid acp 2>>{shlex.quote(str(log_path))}"
    os.execvp(toad_path, [toad_path, "acp", cmd, "-t", "Transactoid"])  # noqa: S606


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    """CLI callback that runs Toad UI by default when no subcommand is provided."""
    # If no subcommand was invoked, launch Toad
    if ctx.invoked_subcommand is None:
        _launch_toad()


@app.command("sync")
def sync(access_token: str, cursor: str | None = None, count: int = 500) -> None:
    """
    Sync transactions from Plaid and categorize them using an LLM.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
    """
    return None


@app.command("ask")
def ask(question: str) -> None:
    return None


@app.command("recat")
def recat(merchant_id: int, to: str) -> None:
    return None


@app.command("tag")
def tag(rows: list[int], tags: list[str]) -> None:
    return None


@app.command("init-db")
def init_db(url: str | None = None) -> None:
    return None


@app.command("seed-taxonomy")
def seed_taxonomy(yaml_path: str = "configs/taxonomy.yaml") -> None:
    return None


@app.command("clear-cache")
def clear_cache(namespace: str = "default") -> None:
    return None


async def _categorize_impl(
    source: str | None,
    batch_size: int,
    dry_run: bool,
) -> None:
    """Categorize uncategorized derived transactions via LLM."""
    from models.transaction import Transaction
    from transactoid.taxonomy.loader import load_taxonomy_from_db
    from transactoid.tools.categorize.categorizer_tool import Categorizer

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    uncategorized_ids = db.get_uncategorized_derived_ids(source=source)
    if not uncategorized_ids:
        typer.echo("No uncategorized transactions found.")
        return

    source_label = f" (source={source})" if source else ""
    count = len(uncategorized_ids)
    typer.echo(f"Found {count} uncategorized transactions{source_label}.")

    if dry_run:
        typer.echo("Dry run — no changes made.")
        return

    taxonomy = load_taxonomy_from_db(db)
    categorizer = Categorizer(taxonomy)

    derived_txns = db.get_derived_transactions_by_ids(uncategorized_ids)

    txn_dicts: list[Transaction] = [
        cast(
            Transaction,
            {
                "transaction_id": txn.external_id,
                "date": txn.posted_at.isoformat(),
                "amount": txn.amount_cents / 100.0,
                "merchant_name": txn.merchant_descriptor,
                "name": txn.merchant_descriptor or "",
                "account_id": "",
                "iso_currency_code": "USD",
            },
        )
        for txn in derived_txns
    ]

    txn_count = len(txn_dicts)
    typer.echo(f"Categorizing {txn_count} transactions (batch_size={batch_size})...")
    categorized = await categorizer.categorize(txn_dicts, batch_size=batch_size)

    external_to_id = {txn.external_id: txn.transaction_id for txn in derived_txns}

    unique_keys: set[str] = set()
    for cat_txn in categorized:
        key = (
            cat_txn.revised_category_key
            if cat_txn.revised_category_key
            else cat_txn.category_key
        )
        if key:
            unique_keys.add(key)

    category_id_map = db.get_category_ids_by_keys(list(unique_keys))

    category_updates: dict[int, int] = {}
    for cat_txn in categorized:
        external_id = cat_txn.txn.get("transaction_id") or ""
        transaction_id = external_to_id.get(str(external_id))
        if transaction_id is None:
            continue
        category_key: str | None = (
            cat_txn.revised_category_key
            if cat_txn.revised_category_key
            else cat_txn.category_key
        )
        if not category_key:
            continue
        category_id = category_id_map.get(category_key)
        if category_id:
            category_updates[transaction_id] = category_id

    if category_updates:
        updated = db.bulk_update_derived_categories(
            category_updates,
            method="llm",
            model=categorizer.model_name,
            reason="cli_categorize",
        )
        typer.echo(f"Updated {updated} transactions.")
    else:
        typer.echo("No categories resolved — 0 transactions updated.")


@app.command("categorize")
def categorize_cmd(
    source: str | None = typer.Option(
        None,
        "--source",
        help="Filter by source (e.g., XLSX_IMPORT, PLAID_INVESTMENT, PLAID).",
    ),
    batch_size: int = typer.Option(
        25,
        "--batch-size",
        help="LLM batch size.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show count of uncategorized transactions without calling LLM.",
    ),
) -> None:
    """Categorize uncategorized transactions using LLM.

    Finds all derived_transactions with no category and runs them through
    the LLM categorizer pipeline.

    Examples:

        # Preview what would be categorized
        transactoid categorize --dry-run

        # Categorize all uncategorized transactions
        transactoid categorize

        # Categorize only XLSX imports
        transactoid categorize --source XLSX_IMPORT
    """
    asyncio.run(_categorize_impl(source=source, batch_size=batch_size, dry_run=dry_run))


@app.command("plaid-serve")
def plaid_serve(
    host: str = typer.Option(
        "localhost",
        help="Host for the local HTTPS redirect server",
    ),
    port: int = typer.Option(
        8443,
        help="Port for redirect server",
    ),
) -> None:
    """
    Start the Plaid OAuth redirect server.

    Starts a local HTTPS redirect server that captures OAuth callbacks from
    Plaid Link. Run this before using the agent to connect new accounts.

    The redirect URI to register in Plaid dashboard:
    https://localhost:8443/plaid-link-complete

    Press Ctrl+C to stop the server.
    """
    import ipaddress
    import queue

    from transactoid.adapters.clients.plaid_link import (
        RedirectServerError,
        shutdown_redirect_server,
        start_redirect_server,
    )

    redirect_path = "/plaid-link-complete"
    token_queue: queue.Queue[str] = queue.Queue()
    state: dict[str, Any] = {}

    try:
        server, server_thread, bound_host, bound_port = start_redirect_server(
            host=host,
            port=port,
            path=redirect_path,
            token_queue=token_queue,
            state=state,
        )
    except (RedirectServerError, OSError) as e:
        typer.echo(f"Failed to start redirect server on {host}:{port}: {e}", err=True)
        raise typer.Exit(1) from None

    # Build redirect URI for display
    redirect_host = host or bound_host
    try:
        host_is_unspecified = ipaddress.ip_address(redirect_host).is_unspecified
    except ValueError:
        host_is_unspecified = redirect_host == ""
    if host_is_unspecified:
        redirect_host = "localhost"
    redirect_uri = f"https://{redirect_host}:{bound_port}{redirect_path}"

    typer.echo(f"Plaid redirect server running at {redirect_uri}")
    typer.echo("Press Ctrl+C to stop.")

    try:
        # Keep running until interrupted
        server_thread.join()
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
    finally:
        shutdown_redirect_server(server, server_thread)


@app.command("connect-account")
def connect_account() -> None:
    """
    Connect a new bank account via Plaid Link.

    Opens Plaid Link in your browser for you to authorize a new bank connection.
    Supports transactions and investments (where available).

    Prerequisites:
        Start the Plaid redirect server in another terminal:
        transactoid plaid-serve

    After authorization:
    - New accounts are automatically saved to the database
    - Investments data will sync on next run
    - Re-linking existing accounts updates credentials and resets sync cursor
    """
    from transactoid.adapters.clients.plaid import PlaidClient

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    try:
        plaid_client = PlaidClient.from_env()
    except Exception as e:
        typer.echo(f"Error initializing Plaid client: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo("Connecting new account via Plaid Link...")
    result = plaid_client.connect_new_account(db=db)

    status = result.get("status", "error")
    message = result.get("message", "Unknown error")

    if status == "success":
        typer.echo("\n✓ Connection successful!")
        typer.echo(f"  Item ID: {result.get('item_id')}")
        typer.echo(f"  Institution: {result.get('institution_name')}")
        typer.echo(f"  Accounts linked: {result.get('accounts_linked', 0)}")
    elif status == "refreshed":
        typer.echo("\n⟳ Connection refreshed!")
        typer.echo(f"  Item ID: {result.get('item_id')}")
        typer.echo(f"  Institution: {result.get('institution_name')}")
        typer.echo(f"  Accounts linked: {result.get('accounts_linked', 0)}")
        if result.get("sync_cursor_reset"):
            typer.echo("  Sync cursor reset - will backfill transaction history")
    else:
        typer.echo(f"\n✗ Connection failed: {message}", err=True)
        raise typer.Exit(1)


@app.command("scrape-amazon")
def scrape_amazon(
    max_orders: int | None = typer.Option(
        None, help="Max orders to scrape (all if not set)"
    ),
    year: int | None = typer.Option(None, help="Filter orders by year (e.g., 2025)"),
    backend: str = typer.Option(
        "stagehand",
        help="Backend: stagehand (local), stagehand-browserbase (cloud), playwriter",
    ),
    context_id: str | None = typer.Option(
        None, help="Browserbase context ID for pre-authenticated sessions"
    ),
    create_context: bool = typer.Option(
        False,
        "--create-context",
        help="Create a new Browserbase context and exit",
    ),
    login: bool = typer.Option(
        False,
        "--login",
        help="Wait for manual login via Session Live View (for first-time auth)",
    ),
) -> None:
    """
    Scrape Amazon order history using browser automation.

    Examples:
        # Local browser (opens visible window for login)
        transactoid scrape-amazon --backend stagehand

        # Create a Browserbase context (one-time setup)
        transactoid scrape-amazon --backend stagehand-browserbase --create-context

        # First-time login with Browserbase (opens Live View for auth)
        transactoid scrape-amazon --backend stagehand-browserbase --context-id ID \\
            --login

        # Use Browserbase with existing authenticated context
        transactoid scrape-amazon --backend stagehand-browserbase --context-id <id>
    """
    from transactoid.tools.amazon.scraper import scrape_amazon_orders

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    if create_context:
        if backend != "stagehand-browserbase":
            typer.echo("Error: --create-context only works with stagehand-browserbase")
            raise typer.Exit(1)

        from transactoid.tools.amazon.backends.stagehand_browserbase import (
            StagehandBrowserbaseBackend,
        )

        typer.echo("Creating new Browserbase context...")
        new_context_id = StagehandBrowserbaseBackend.create_context()
        typer.echo("\nContext created successfully!")
        typer.echo(f"Context ID: {new_context_id}")
        typer.echo("\nUse this context for future scrapes:")
        typer.echo(
            f"  transactoid scrape-amazon --backend stagehand-browserbase "
            f"--context-id {new_context_id}"
        )
        return

    if backend not in ("stagehand", "stagehand-browserbase", "playwriter"):
        typer.echo(f"Error: Invalid backend '{backend}'")
        raise typer.Exit(1)

    if login and backend != "stagehand-browserbase":
        typer.echo("Error: --login only works with stagehand-browserbase backend")
        raise typer.Exit(1)

    typer.echo(f"Scraping Amazon orders (backend={backend}, max_orders={max_orders})")
    if year:
        typer.echo(f"Filtering by year: {year}")
    if context_id:
        typer.echo(f"Using context: {context_id}")
    if login:
        typer.echo("Login mode: waiting for manual auth via Session Live View")

    result = scrape_amazon_orders(
        db,
        backend=backend,  # type: ignore[arg-type]
        year=year,
        max_orders=max_orders,
        context_id=context_id,
        login_mode=login,
    )

    if result.get("status") == "success":
        typer.echo("\nSuccess!")
        typer.echo(f"  Orders created: {result.get('orders_created', 0)}")
        typer.echo(f"  Items created: {result.get('items_created', 0)}")
    else:
        typer.echo(f"\nError: {result.get('message', 'Unknown error')}")
        raise typer.Exit(1)


@app.command("reset-investment-watermark")
def reset_investment_watermark(
    item_id: str | None = typer.Option(
        None,
        "--item-id",
        help="Plaid item ID to reset. If omitted, resets all items.",
    ),
) -> None:
    """
    Reset investment sync watermark to force full historical backfill.

    By default, investment syncs only fetch transactions since the last
    watermark. Resetting the watermark forces a full backfill of up to
    730 days of investment history on the next sync.

    Args:
        item_id: Plaid item ID to reset. If omitted, resets all connected items.

    Example:
        # Reset a specific item
        transactoid reset-investment-watermark --item-id abc123xyz

        # Reset all items
        transactoid reset-investment-watermark
    """
    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    if item_id:
        # Reset specific item
        try:
            db.set_investments_watermark(item_id, None)  # type: ignore[arg-type]
            typer.echo(f"✓ Investment watermark reset for item {item_id[:8]}...")
        except Exception as e:
            typer.echo(f"✗ Failed to reset watermark: {e}", err=True)
            raise typer.Exit(1) from e
    else:
        # Reset all items
        items = db.list_plaid_items()
        if not items:
            typer.echo("No Plaid items found.")
            return

        reset_count = 0
        for item in items:
            try:
                db.set_investments_watermark(item.item_id, None)  # type: ignore[arg-type]
                reset_count += 1
                typer.echo(f"✓ Reset: {item.item_id[:8]}... ({item.institution_name})")
            except Exception as e:
                typer.echo(f"✗ Failed to reset {item.item_id}: {e}", err=True)

        typer.echo(f"\nWatermarks reset for {reset_count}/{len(items)} items.")
        typer.echo("Next sync will backfill up to 730 days of investment history.")


@app.command("plaid-dedupe-items")
def plaid_dedupe_items(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete duplicate items. Default is dry-run.",
    ),
) -> None:
    """
    Find and remove duplicate Plaid items based on (institution_id, mask) dedupe key.

    Groups items by their account dedupe keys (fetched live from Plaid API) and
    keeps the earliest created item, deleting any duplicates.

    Dry-run by default. Use --apply to actually delete duplicates.
    """
    from collections import defaultdict

    from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    # Initialize Plaid client
    try:
        plaid_client = PlaidClient.from_env()
    except PlaidClientError as e:
        typer.echo(f"Error initializing Plaid client: {e}", err=True)
        raise typer.Exit(1) from None

    # Get all items
    items = db.list_plaid_items()
    if not items:
        typer.echo("No Plaid items found.")
        return

    # Build dedupe key -> items mapping by fetching accounts live
    dedupe_groups: dict[tuple[str | None, str | None], list[tuple[str, datetime]]] = (
        defaultdict(list)
    )
    items_with_errors: list[tuple[str, str]] = []

    typer.echo(f"Fetching accounts for {len(items)} items from Plaid API...")

    for item in items:
        try:
            accounts = plaid_client.get_accounts(item.access_token)
            if not accounts:
                items_with_errors.append((item.item_id, "No accounts returned"))
                continue

            for account in accounts:
                dedupe_key = (item.institution_id, account.get("mask"))
                dedupe_groups[dedupe_key].append((item.item_id, item.created_at))

        except PlaidClientError as e:
            items_with_errors.append((item.item_id, str(e)))
            continue

    # Find duplicates
    to_keep: set[str] = set()
    to_delete: set[str] = set()

    for _dedupe_key, item_list in dedupe_groups.items():
        if len(item_list) <= 1:
            # No duplicates for this key
            for item_id, _ in item_list:
                to_keep.add(item_id)
            continue

        # Sort by created_at (earliest first), then item_id for tie-breaker
        sorted_items = sorted(item_list, key=lambda x: (x[1], x[0]))
        canonical_item_id = sorted_items[0][0]
        to_keep.add(canonical_item_id)

        for item_id, _ in sorted_items[1:]:
            to_delete.add(item_id)

    # Report results
    typer.echo(f"\n{'=' * 60}")
    typer.echo("Plaid Item Dedupe Report")
    typer.echo(f"{'=' * 60}\n")

    typer.echo(f"Total items scanned: {len(items)}")
    typer.echo(f"Items to keep: {len(to_keep)}")
    typer.echo(f"Items to delete: {len(to_delete)}")
    typer.echo(f"Items with API errors (skipped): {len(items_with_errors)}")

    if items_with_errors:
        typer.echo("\nSkipped items (API errors):")
        for item_id, error in items_with_errors:
            typer.echo(f"  - {item_id}: {error}")

    if to_delete:
        typer.echo("\nDuplicate items to delete:")
        for item_id in sorted(to_delete):
            typer.echo(f"  - {item_id}")

    if to_keep:
        typer.echo("\nItems to keep:")
        for item_id in sorted(to_keep):
            typer.echo(f"  + {item_id}")

    # Apply deletions if requested
    if to_delete:
        if apply:
            typer.echo(f"\n{'=' * 60}")
            typer.echo("Applying deletions...")
            deleted_count = 0
            for item_id in to_delete:
                if db.delete_plaid_item(item_id):
                    deleted_count += 1
                    typer.echo(f"  Deleted: {item_id}")
            typer.echo(f"\nDeleted {deleted_count} duplicate items.")
        else:
            typer.echo(f"\n{'=' * 60}")
            typer.echo("DRY RUN - No changes made.")
            typer.echo("Run with --apply to delete duplicate items.")
    else:
        typer.echo("\nNo duplicates found. Database is clean.")


@app.command("plaid-cleanup-investment-dupes")
def plaid_cleanup_investment_dupes(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete. Default is dry-run.",
    ),
) -> None:
    """
    Find and remove PLAID_INVESTMENT rows that duplicate existing PLAID rows.

    Matches on (item_id, account_id, posted_at, amount_cents). Archives
    duplicates to R2 before deletion.

    Dry-run by default. Use --apply to actually delete duplicates.
    """
    from collections import defaultdict

    from transactoid.adapters.storage.archive import (
        archive_investment_dupes_to_r2,
    )

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    dupes = db.find_investment_dupes_with_plaid_match()
    if not dupes:
        typer.echo("No duplicates found.")
        return

    # Group by item_id
    by_item: dict[str, list[Any]] = defaultdict(list)
    for txn in dupes:
        by_item[txn.item_id or "unknown"].append(txn)

    # Report
    typer.echo(f"\n{'=' * 60}")
    typer.echo("PLAID_INVESTMENT Duplicate Report")
    typer.echo(f"{'=' * 60}\n")
    typer.echo(f"Total duplicates: {len(dupes)}")

    for item_id, txns in sorted(by_item.items()):
        typer.echo(f"\nItem {item_id}:")
        for txn in sorted(txns, key=lambda t: t.posted_at):
            amount_str = f"${txn.amount_cents / 100:,.2f}"
            typer.echo(
                f"  {txn.posted_at}  {amount_str:>12}  "
                f"{txn.merchant_descriptor or '(no descriptor)'}"
            )

    if apply:
        typer.echo(f"\n{'=' * 60}")
        typer.echo("Applying deletions...")

        for item_id, txns in by_item.items():
            records: list[dict[str, Any]] = [
                {
                    "external_id": txn.external_id,
                    "account_id": txn.account_id,
                    "posted_at": txn.posted_at,
                    "amount_cents": txn.amount_cents,
                    "merchant_descriptor": txn.merchant_descriptor,
                }
                for txn in txns
            ]
            archive_investment_dupes_to_r2(
                item_id=item_id,
                records=records,
                key_prefix="investment-dedup-cleanup",
            )

            external_ids = [txn.external_id for txn in txns]
            deleted = db.delete_plaid_transactions_by_external_ids(
                external_ids, source="PLAID_INVESTMENT"
            )
            typer.echo(f"  Deleted {deleted} transactions for item {item_id}")

        typer.echo(f"\nDone. Deleted {len(dupes)} duplicate transactions.")
    else:
        typer.echo(f"\n{'=' * 60}")
        typer.echo("DRY RUN - No changes made.")
        typer.echo("Run with --apply to delete duplicate transactions.")


@app.command()
def agent() -> None:
    """
    Run the interactive Transactoid agent via Toad UI.

    Launches Toad ACP client connected to the Transactoid ACP server.
    """
    _launch_toad()


@app.command()
def acp() -> None:
    """
    Run the ACP (Agent Client Protocol) server.

    Starts the Transactoid agent as an ACP server that communicates via
    JSON-RPC over stdin/stdout. Use this with ACP clients like Toad:

        toad acp "transactoid acp"
    """
    from transactoid.ui.acp.server import main as acp_main

    asyncio.run(acp_main())


async def _eval_impl(
    questions_path: str,
    questions: str | None,
    output_dir: str,
) -> None:
    """
    Run the evaluation suite against the agent.

    Executes the agent against predefined questions with synthetic data,
    evaluates responses using an LLM judge, and generates results.
    """
    from evals.core.eval_harness import EvalHarness

    # Run harness
    harness = EvalHarness(questions_path, questions=questions)
    results = await harness.run_all()

    # Save and display results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(output_dir, exist_ok=True)
    output_path = f"{output_dir}/eval_run_{timestamp}.json"
    harness.save_results(results, output_path)
    harness.print_summary(results)

    print(f"\nResults saved to: {output_path}")


@app.command("eval")
def eval_cmd(
    input: str = typer.Option(
        "evals/config/questions.yaml",
        "--input",
        help="Path to questions.yaml file",
    ),
    questions: str | None = typer.Option(
        None,
        "--questions",
        help="Comma-separated question IDs (e.g., q001,q003). Runs all if omitted.",
    ),
    output_dir: str = typer.Option(
        ".eval_results",
        "--output-dir",
        help="Output directory for results",
    ),
) -> None:
    """Run the evaluation suite against the Transactoid agent."""
    asyncio.run(
        _eval_impl(questions_path=input, questions=questions, output_dir=output_dir)
    )


async def _agent_run_impl(
    prompt: str | None,
    prompt_key: str | None,
    continue_run_id: str | None,
    email: list[str],
    save_md: bool,
    save_html: bool,
    output_target: list[str],
    local_dir: str | None,
    max_turns: int,
    template_vars: dict[str, str] | None = None,
) -> None:
    """Execute an agent run via AgentRunService."""
    from transactoid.services.agent_run import (
        AgentRunRequest,
        AgentRunService,
        OutputTarget,
    )
    from transactoid.services.agent_run.pipeline import OutputPipeline
    from transactoid.taxonomy.loader import load_taxonomy_from_db

    targets = tuple(OutputTarget(target) for target in output_target)

    request = AgentRunRequest(
        prompt=prompt,
        prompt_key=prompt_key,
        template_vars=template_vars or {},
        continue_run_id=continue_run_id,
        save_md=save_md,
        save_html=save_html,
        output_targets=targets,
        local_dir=local_dir,
        email_recipients=tuple(email),
        max_turns=max_turns,
    )

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)
    taxonomy = load_taxonomy_from_db(db)

    service = AgentRunService(db=db, taxonomy=taxonomy)
    result = await service.execute(request)

    if result.success:
        typer.echo(f"Run {result.run_id} completed in {result.duration_seconds:.1f}s")

        pipeline = OutputPipeline()
        html_text, artifacts = pipeline.process(
            report_text=result.report_text, request=request, run_id=result.run_id
        )

        for artifact in artifacts:
            typer.echo(f"  {artifact.artifact_type}: {artifact.key}")

        if email:
            _send_run_email(
                report_text=result.report_text,
                prompt_key=prompt_key,
                recipients=email,
                html_content=html_text,
            )
        elif not artifacts:
            typer.echo("\n" + result.report_text)
    else:
        typer.echo(f"Run {result.run_id} failed: {result.error}", err=True)
        raise typer.Exit(1)


@app.command("run")
def run_cmd(
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        help="Raw prompt text to send to the agent",
    ),
    prompt_key: str | None = typer.Option(
        None,
        "--prompt-key",
        help="Promptorium key to load (e.g. 'report-monthly')",
    ),
    continue_run_id: str | None = typer.Option(
        None,
        "--continue",
        help="Resume a previous run by run ID",
    ),
    email: list[str] | None = typer.Option(
        None,
        "--email",
        help="Email recipient(s) for the report (repeatable)",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        help="Maximum agent turns",
    ),
    save_md: bool = typer.Option(
        True,
        "--save-md/--no-save-md",
        help="Save markdown artifact",
    ),
    save_html: bool = typer.Option(
        True,
        "--save-html/--no-save-html",
        help="Save HTML artifact",
    ),
    output_target: list[str] | None = typer.Option(
        None,
        "--output-target",
        help="Output target: 'r2' or 'local' (repeatable, default: r2)",
    ),
    local_dir: str | None = typer.Option(
        None,
        "--local-dir",
        help="Local directory for artifact output",
    ),
) -> None:
    """Execute a headless agent run.

    Run the Transactoid agent with a prompt (raw text or promptorium key)
    and optionally email the output.

    Examples:

        # Run a monthly report
        transactoid run --prompt-key report-monthly

        # Run with a raw prompt
        transactoid run --prompt "Summarize my spending"

        # Continue a previous run
        transactoid run --prompt "Add more detail" --continue abc123

        # Email the report
        transactoid run --prompt-key report-monthly --email user@example.com
    """
    if prompt is None and prompt_key is None:
        typer.echo("Either --prompt or --prompt-key is required", err=True)
        raise typer.Exit(1)

    if prompt is not None and prompt_key is not None:
        typer.echo("Only one of --prompt or --prompt-key may be provided", err=True)
        raise typer.Exit(1)

    targets = output_target or ["r2"]
    valid_targets = {"r2", "local"}
    for target in targets:
        if target not in valid_targets:
            typer.echo(f"Invalid output target: {target}", err=True)
            raise typer.Exit(1)

    asyncio.run(
        _agent_run_impl(
            prompt=prompt,
            prompt_key=prompt_key,
            continue_run_id=continue_run_id,
            email=email or [],
            save_md=save_md,
            save_html=save_html,
            output_target=targets,
            local_dir=local_dir,
            max_turns=max_turns,
        )
    )


_DEFAULT_EMAIL_CONFIG_PATH = "configs/email.yaml"
_DEFAULT_SCHEDULED_EMAIL_RECIPIENTS = ("adambossy@gmail.com",)
_DEFAULT_VERIFIED_FROM_ADDRESS = "onboarding@resend.dev"


def _load_email_config() -> dict[str, Any]:
    """Load email configuration from configs/email.yaml."""
    path = Path(_DEFAULT_EMAIL_CONFIG_PATH)
    if not path.exists():
        typer.echo(f"Config file not found: {_DEFAULT_EMAIL_CONFIG_PATH}", err=True)
        raise typer.Exit(1)

    with open(path) as f:
        config: dict[str, Any] = yaml.safe_load(f)
        return config


def _send_run_email(
    *,
    report_text: str,
    prompt_key: str | None,
    recipients: list[str],
    html_content: str | None = None,
) -> None:
    """Send email after a completed agent run.

    Loads sender/subject defaults from configs/email.yaml. If the agent wrote
    an HTML file at the standardized path, attaches it as the HTML body.
    """
    from transactoid.services.email_service import EmailService, SMTPConfig

    config = _load_email_config()
    email_config: dict[str, Any] = config.get("email", {})

    now = datetime.now()
    subject_template: str = email_config.get(
        "subject_template", "Transactoid Report - {month} {year}"
    )
    subject = subject_template.format(month=now.strftime("%B"), year=now.year)

    # Prefer pipeline-generated HTML; fallback to standardized report file path.
    resolved_html_content = html_content
    if resolved_html_content is None and prompt_key:
        html_path = Path(f".transactoid/reports/{prompt_key}-latest.html")
        if html_path.exists():
            resolved_html_content = html_path.read_text()

    configured_from_address = email_config.get(
        "from_address", _DEFAULT_VERIFIED_FROM_ADDRESS
    )
    from_address = str(configured_from_address)
    provider = str(email_config.get("provider", "resend")).strip().lower()
    if provider == "resend" and from_address.endswith("@transactoid.com"):
        typer.echo(
            "Configured from_address is unverified; using onboarding@resend.dev",
            err=True,
        )
        from_address = _DEFAULT_VERIFIED_FROM_ADDRESS

    def _coerce_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    smtp_config: SMTPConfig | None = None
    if provider == "smtp":
        smtp_host = str(
            email_config.get("smtp_host") or os.environ.get("SMTP_HOST", "")
        )
        smtp_port_value = email_config.get("smtp_port") or os.environ.get(
            "SMTP_PORT", "587"
        )
        smtp_port = int(str(smtp_port_value))
        smtp_username = str(
            email_config.get("smtp_username") or os.environ.get("SMTP_USERNAME", "")
        )
        smtp_password = str(
            email_config.get("smtp_password") or os.environ.get("SMTP_PASSWORD", "")
        )
        smtp_use_tls = _coerce_bool(
            email_config.get("smtp_use_tls", os.environ.get("SMTP_USE_TLS")),
            default=True,
        )
        smtp_use_ssl = _coerce_bool(
            email_config.get("smtp_use_ssl", os.environ.get("SMTP_USE_SSL")),
            default=False,
        )
        smtp_config = SMTPConfig(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            use_tls=smtp_use_tls,
            use_ssl=smtp_use_ssl,
        )

    try:
        email_service = EmailService(
            from_address=from_address,
            from_name=email_config.get("from_name", "Transactoid Reports"),
            provider=provider,
            smtp_config=smtp_config,
        )
    except ValueError as exc:
        typer.echo(f"Email service error: {exc}", err=True)
        raise typer.Exit(1) from None

    safe_text_content = report_text.strip() or "Transactoid generated a report."
    safe_html_content = (
        resolved_html_content or f"<pre>{escape(safe_text_content)}</pre>"
    )

    email_result = email_service.send_report(
        to=recipients,
        subject=subject,
        html_content=safe_html_content,
        text_content=safe_text_content,
    )

    if email_result.success:
        typer.echo(f"Report sent to: {', '.join(recipients)}")
    else:
        typer.echo(f"Failed to send email: {email_result.error}", err=True)
        raise typer.Exit(1)


@app.command("run-scheduled-report")
def run_scheduled_report_cmd(
    email: list[str] | None = typer.Option(
        None,
        "--email",
        help="Email recipient(s) for the report (repeatable)",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        help="Maximum agent turns",
    ),
) -> None:
    """Run the scheduled report with New York-time precedence rules."""
    now_utc = datetime.now(UTC)
    now_ny = now_utc.astimezone(NEW_YORK_TZ)

    selected_prompt_key = select_prompt_key(now_utc=now_utc)
    recipients = email or list(_DEFAULT_SCHEDULED_EMAIL_RECIPIENTS)
    typer.echo(
        f"Selected scheduled report prompt: {selected_prompt_key} "
        f"({now_ny.strftime('%Y-%m-%d %H:%M:%S %Z')})"
    )

    asyncio.run(
        _agent_run_impl(
            prompt=None,
            prompt_key=selected_prompt_key,
            continue_run_id=None,
            email=recipients,
            save_md=True,
            save_html=True,
            output_target=["r2"],
            local_dir=None,
            max_turns=max_turns,
        )
    )


def main() -> None:
    app()
