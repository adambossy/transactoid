from __future__ import annotations

import asyncio
from datetime import datetime
import os

from dotenv import load_dotenv
import typer

from scripts import run
from transactoid.adapters.db.facade import DB
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db

# Load environment variables from .env
load_dotenv()

app = typer.Typer(
    help="Transactoid — personal finance agent CLI.",
    invoke_without_command=True,
    no_args_is_help=False,
)

run_app = typer.Typer(help="Run pipeline workflows.")
app.add_typer(run_app, name="run")


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    """CLI callback that runs agent by default when no subcommand is provided."""
    # If no subcommand was invoked, run the agent
    if ctx.invoked_subcommand is None:
        asyncio.run(_agent_impl())


@run_app.command("sync")
def run_sync_cmd(
    access_token: str = typer.Option(..., help="Plaid access token for the item"),
    cursor: str | None = typer.Option(
        None, help="Optional cursor for incremental sync"
    ),
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
) -> None:
    """Sync transactions from Plaid and categorize them using an LLM."""
    run.run_sync(access_token=access_token, cursor=cursor, count=count)


@run_app.command("pipeline")
def run_pipeline_cmd(
    access_token: str = typer.Option(..., help="Plaid access token for the item"),
    cursor: str | None = typer.Option(
        None, help="Optional cursor for incremental sync"
    ),
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
    questions: list[str] | None = typer.Option(  # noqa: B008
        None, help="Optional questions for analytics"
    ),
) -> None:
    """Run the full pipeline: sync → categorize → persist."""
    run.run_pipeline(
        access_token=access_token, cursor=cursor, count=count, questions=questions
    )


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
    from typing import Any

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


async def _agent_impl(
    *,
    db: DB | None = None,
    taxonomy: Taxonomy | None = None,
) -> None:
    """
    Run the interactive agent loop using OpenAI Agents SDK.

    The agent helps users understand and manage their personal finances
    through a conversational interface with access to transaction data.
    """
    # Initialize services
    if db is None:
        db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        db = DB(db_url)

    if taxonomy is None:
        taxonomy = load_taxonomy_from_db(db)

    agent_instance = Transactoid(db=db, taxonomy=taxonomy)
    await agent_instance.run()


@app.command()
def agent() -> None:
    """
    Run the interactive Transactoid agent.

    The agent helps you understand and manage your personal finances
    through a conversational interface with access to transaction data.
    """
    asyncio.run(_agent_impl())


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


def main() -> None:
    app()
