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

    Groups items by their account dedupe keys and keeps the earliest created item,
    deleting any duplicates. Items without plaid_accounts are skipped and reported.

    Dry-run by default. Use --apply to actually delete duplicates.
    """
    from collections import defaultdict

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    # Get all items and accounts
    items = db.list_plaid_items()
    if not items:
        typer.echo("No Plaid items found.")
        return

    # Build dedupe key -> items mapping
    dedupe_groups: dict[tuple[str | None, str | None], list[tuple[str, datetime]]] = (
        defaultdict(list)
    )
    items_without_accounts: list[str] = []

    for item in items:
        accounts = db.get_plaid_accounts_for_item(item.item_id)
        if not accounts:
            items_without_accounts.append(item.item_id)
            continue

        for account in accounts:
            dedupe_key = (account.institution_id, account.mask)
            dedupe_groups[dedupe_key].append((item.item_id, item.created_at))

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
    typer.echo(f"\n{'='*60}")
    typer.echo("Plaid Item Dedupe Report")
    typer.echo(f"{'='*60}\n")

    typer.echo(f"Total items scanned: {len(items)}")
    typer.echo(f"Items to keep: {len(to_keep)}")
    typer.echo(f"Items to delete: {len(to_delete)}")
    typer.echo(f"Items without accounts (skipped): {len(items_without_accounts)}")

    if items_without_accounts:
        skipped = ", ".join(items_without_accounts)
        typer.echo(f"\nSkipped items (no accounts): {skipped}")

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
            typer.echo(f"\n{'='*60}")
            typer.echo("Applying deletions...")
            deleted_count = 0
            for item_id in to_delete:
                if db.delete_plaid_item(item_id):
                    deleted_count += 1
                    typer.echo(f"  Deleted: {item_id}")
            typer.echo(f"\nDeleted {deleted_count} duplicate items.")
        else:
            typer.echo(f"\n{'='*60}")
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
        help="Comma-separated question IDs to run (e.g., q001,q003,q005). If not provided, runs all.",
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
