from __future__ import annotations

import asyncio
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any

from dotenv import load_dotenv
import typer
import yaml

from scripts import run
from transactoid.adapters.db.facade import DB

# Load environment variables from .env
load_dotenv()

app = typer.Typer(
    help="Transactoid — personal finance agent CLI.",
    invoke_without_command=True,
    no_args_is_help=False,
)

run_app = typer.Typer(help="Run pipeline workflows.")
app.add_typer(run_app, name="run")


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

    cmd = "uv run transactoid acp 2>/tmp/transactoid.log"
    os.execvp(toad_path, [toad_path, "acp", cmd, "-t", "Transactoid"])  # noqa: S606


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    """CLI callback that runs Toad UI by default when no subcommand is provided."""
    # If no subcommand was invoked, launch Toad
    if ctx.invoked_subcommand is None:
        _launch_toad()


@run_app.command("sync")
def run_sync_cmd(
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
) -> None:
    """Sync transactions from all Plaid items and categorize them using an LLM."""
    run.run_sync(count=count)


@run_app.command("pipeline")
def run_pipeline_cmd(
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
    questions: list[str] | None = typer.Option(  # noqa: B008
        None, help="Optional questions for analytics"
    ),
) -> None:
    """Run the full pipeline: sync → categorize → persist."""
    run.run_pipeline(count=count, questions=questions)


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


@app.command("scrape-amazon")
def scrape_amazon(
    max_orders: int = typer.Option(10, help="Maximum number of orders to scrape"),
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
) -> None:
    """
    Scrape Amazon order history using browser automation.

    Examples:
        # Local browser (opens visible window for login)
        transactoid scrape-amazon --backend stagehand

        # Create a Browserbase context (one-time setup)
        transactoid scrape-amazon --backend stagehand-browserbase --create-context

        # Use Browserbase with existing context
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

    typer.echo(f"Scraping Amazon orders (backend={backend}, max_orders={max_orders})")
    if context_id:
        typer.echo(f"Using context: {context_id}")

    result = scrape_amazon_orders(
        db,
        backend=backend,  # type: ignore[arg-type]
        max_orders=max_orders,
        context_id=context_id,
    )

    if result.get("status") == "success":
        typer.echo("\nSuccess!")
        typer.echo(f"  Orders created: {result.get('orders_created', 0)}")
        typer.echo(f"  Items created: {result.get('items_created', 0)}")
    else:
        typer.echo(f"\nError: {result.get('message', 'Unknown error')}")
        raise typer.Exit(1)


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


def _load_report_config(config_path: str) -> dict[str, Any]:
    """Load report configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        typer.echo(f"Config file not found: {config_path}", err=True)
        raise typer.Exit(1)

    with open(path) as f:
        config: dict[str, Any] = yaml.safe_load(f)
        return config


async def _report_impl(
    send_email: bool,
    output_file: str | None,
    config_path: str,
    report_month: str | None = None,
) -> None:
    """Generate spending report implementation."""
    from transactoid.jobs.report.email_service import EmailService
    from transactoid.jobs.report.html_renderer import render_report_html
    from transactoid.jobs.report.runner import ReportRunner
    from transactoid.taxonomy.loader import load_taxonomy_from_db

    # Load config
    config = _load_report_config(config_path)
    email_config = config.get("email", {})
    error_config = config.get("error_notification", {})

    # Initialize database
    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)

    # Load taxonomy
    taxonomy = load_taxonomy_from_db(db)

    # Create report runner
    runner = ReportRunner(db=db, taxonomy=taxonomy)

    month_str = f" for {report_month}" if report_month else ""
    typer.echo(f"Generating spending report{month_str}...")
    result = await runner.generate_report(report_month=report_month)

    if result.success:
        typer.echo(f"Report generated in {result.duration_seconds:.1f}s")

        # Generate styled HTML version
        html_content = render_report_html(result.report_text)

        # Output to file if requested (both .md and .html)
        if output_file:
            # Write markdown version
            md_path = output_file
            if not md_path.endswith(".md"):
                md_path = f"{output_file}.md"
            with open(md_path, "w") as f:
                f.write(result.report_text)
            typer.echo(f"Markdown report saved to: {md_path}")

            # Write HTML version
            html_path = md_path.replace(".md", ".html")
            with open(html_path, "w") as f:
                f.write(html_content)
            typer.echo(f"HTML report saved to: {html_path}")

        # Send email if requested
        if send_email:
            recipients = email_config.get("recipients", [])
            if not recipients:
                typer.echo("No recipients configured in report.yaml", err=True)
                raise typer.Exit(1)

            # Override from env if set
            env_recipients = os.environ.get("REPORT_RECIPIENTS")
            if env_recipients:
                recipients = [r.strip() for r in env_recipients.split(",")]

            # Build subject
            now = datetime.now()
            subject_template = email_config.get(
                "subject_template", "Transactoid Spending Report - {month} {year}"
            )
            subject = subject_template.format(month=now.strftime("%B"), year=now.year)

            # Initialize email service
            try:
                email_service = EmailService(
                    from_address=email_config.get(
                        "from_address", "reports@transactoid.com"
                    ),
                    from_name=email_config.get("from_name", "Transactoid Reports"),
                )
            except ValueError as e:
                typer.echo(f"Email service error: {e}", err=True)
                raise typer.Exit(1) from None

            # Send report (using styled HTML generated above)
            email_result = email_service.send_report(
                to=recipients,
                subject=subject,
                html_content=html_content,
                text_content=result.report_text,
            )

            if email_result.success:
                typer.echo(f"Report sent to: {', '.join(recipients)}")
            else:
                typer.echo(f"Failed to send email: {email_result.error}", err=True)
                raise typer.Exit(1)
        else:
            # Print report to stdout if not emailing and no output file
            if not output_file:
                typer.echo("\n" + "=" * 60)
                typer.echo(result.report_text)
                typer.echo("=" * 60)

    else:
        typer.echo(f"Report generation failed: {result.error}", err=True)

        # Send error notification if configured
        if error_config.get("enabled", False) and send_email:
            error_recipients = error_config.get("recipients", [])
            if error_recipients:
                try:
                    email_service = EmailService(
                        from_address=email_config.get(
                            "from_address", "reports@transactoid.com"
                        ),
                        from_name=email_config.get("from_name", "Transactoid Reports"),
                    )
                    email_service.send_error_notification(
                        to=error_recipients,
                        error=result.error or "Unknown error",
                        job_metadata=result.metadata,
                    )
                    recipients_str = ", ".join(error_recipients)
                    typer.echo(f"Error notification sent to: {recipients_str}")
                except Exception as e:
                    typer.echo(f"Failed to send error notification: {e}", err=True)

        raise typer.Exit(1)


@app.command("report")
def report_cmd(
    send_email: bool = typer.Option(
        True,
        "--send-email/--no-send-email",
        help="Send report via email (default: True)",
    ),
    output_file: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write report to file instead of (or in addition to) email",
    ),
    config_path: str = typer.Option(
        "configs/report.yaml",
        "--config",
        "-c",
        help="Path to report configuration file",
    ),
    month: str | None = typer.Option(
        None,
        "--month",
        "-m",
        help="Report month in YYYY-MM format (e.g., 2026-01)",
    ),
) -> None:
    """Generate and send a spending report.

    Runs the Transactoid agent headlessly with a detailed spending analysis
    prompt and emails the resulting report.

    Examples:

        # Generate and email report (default)
        transactoid report

        # Generate report without sending email (prints to stdout)
        transactoid report --no-send-email

        # Save report to file
        transactoid report --output /tmp/report.md

        # Save to file and email
        transactoid report --output /tmp/report.md --send-email

        # Generate report for a specific month
        transactoid report --month 2026-01 --output /tmp/january-report
    """
    asyncio.run(_report_impl(send_email, output_file, config_path, month))


def main() -> None:
    app()
