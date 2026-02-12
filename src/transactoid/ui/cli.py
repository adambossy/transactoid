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

from transactoid.adapters.db.facade import DB

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

    cmd = "uv run transactoid acp 2>/tmp/transactoid.log"
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

        if not artifacts and not email:
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
        help="Promptorium key to load (e.g. 'spending-report')",
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
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        help="Maximum agent turns",
    ),
    month: str | None = typer.Option(
        None,
        "--month",
        "-m",
        help="Helper: inject CURRENT_DATE/CURRENT_MONTH/CURRENT_YEAR for YYYY-MM",
    ),
) -> None:
    """Execute a headless agent run.

    Run the Transactoid agent with a prompt (raw text or promptorium key),
    persist artifacts to R2 or local disk, and optionally email the output.

    Examples:

        # Run with a promptorium key
        transactoid run --prompt-key spending-report

        # Run with a raw prompt
        transactoid run --prompt "Summarize my spending"

        # Continue a previous run
        transactoid run --prompt "Add more detail" --continue abc123

        # Save locally instead of R2
        transactoid run --prompt-key spending-report --output-target local

        # Email the report
        transactoid run --prompt-key spending-report --email user@example.com
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

    template_vars: dict[str, str] = {}
    if month and prompt_key:
        template_vars = _build_month_template_vars(month)

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
            template_vars=template_vars or None,
        )
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


def _build_month_template_vars(month: str) -> dict[str, str]:
    """Parse YYYY-MM and return template vars for date injection."""
    import calendar

    year, month_num = map(int, month.split("-"))
    month_name = calendar.month_name[month_num]
    last_day = calendar.monthrange(year, month_num)[1]
    return {
        "CURRENT_DATE": f"{year}-{month_num:02d}-{last_day:02d}",
        "CURRENT_MONTH": month_name,
        "CURRENT_YEAR": str(year),
    }


def _resolve_report_recipients(
    email_config: dict[str, Any],
) -> list[str]:
    """Resolve email recipients from config and env overrides."""
    recipients: list[str] = email_config.get("recipients", [])
    env_recipients = os.environ.get("REPORT_RECIPIENTS")
    if env_recipients:
        recipients = [r.strip() for r in env_recipients.split(",")]
    return recipients


async def _report_impl(
    send_email: bool,
    output_file: str | None,
    config_path: str,
    report_month: str | None = None,
) -> None:
    """Generate spending report by delegating to AgentRunService."""
    from transactoid.jobs.report.email_service import EmailService
    from transactoid.services.agent_run import (
        AgentRunRequest,
        AgentRunService,
        OutputTarget,
    )
    from transactoid.services.agent_run.pipeline import OutputPipeline
    from transactoid.taxonomy.loader import load_taxonomy_from_db

    config = _load_report_config(config_path)
    email_config: dict[str, Any] = config.get("email", {})
    error_config: dict[str, Any] = config.get("error_notification", {})

    template_vars: dict[str, str] = {}
    if report_month:
        template_vars = _build_month_template_vars(report_month)

    # Pipeline handles R2; output_file is written manually below
    output_targets: list[OutputTarget] = [OutputTarget.R2]

    # Resolve email recipients
    email_recipients: list[str] = []
    if send_email:
        email_recipients = _resolve_report_recipients(email_config)
        if not email_recipients:
            typer.echo("No recipients configured in report.yaml", err=True)
            raise typer.Exit(1)

    request = AgentRunRequest(
        prompt_key="spending-report",
        template_vars=template_vars,
        save_md=True,
        save_html=True,
        output_targets=tuple(output_targets),
        email_recipients=tuple(email_recipients),
    )

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)
    taxonomy = load_taxonomy_from_db(db)

    service = AgentRunService(db=db, taxonomy=taxonomy)

    month_str = f" for {report_month}" if report_month else ""
    typer.echo(f"Generating spending report{month_str}...")
    result = await service.execute(request)

    if result.success:
        typer.echo(f"Report generated in {result.duration_seconds:.1f}s")

        pipeline = OutputPipeline()
        html_text, artifacts = pipeline.process(
            report_text=result.report_text, request=request, run_id=result.run_id
        )

        for artifact in artifacts:
            typer.echo(f"  {artifact.artifact_type}: {artifact.key}")

        # Write to specific output file if requested
        if output_file:
            md_path = (
                output_file if output_file.endswith(".md") else (f"{output_file}.md")
            )
            with open(md_path, "w") as fout:
                fout.write(result.report_text)
            typer.echo(f"Markdown report saved to: {md_path}")

            if html_text:
                html_path = md_path.replace(".md", ".html")
                with open(html_path, "w") as fout:
                    fout.write(html_text)
                typer.echo(f"HTML report saved to: {html_path}")

        # Send email if requested
        if send_email and email_recipients:
            now = datetime.now()
            subject_template = email_config.get(
                "subject_template", "Transactoid Spending Report - {month} {year}"
            )
            subject = subject_template.format(month=now.strftime("%B"), year=now.year)

            try:
                email_service = EmailService(
                    from_address=email_config.get(
                        "from_address", "reports@transactoid.com"
                    ),
                    from_name=email_config.get("from_name", "Transactoid Reports"),
                )
            except ValueError as exc:
                typer.echo(f"Email service error: {exc}", err=True)
                raise typer.Exit(1) from None

            email_result = email_service.send_report(
                to=email_recipients,
                subject=subject,
                html_content=html_text or result.report_text,
                text_content=result.report_text,
            )

            if email_result.success:
                typer.echo(f"Report sent to: {', '.join(email_recipients)}")
            else:
                typer.echo(f"Failed to send email: {email_result.error}", err=True)
                raise typer.Exit(1)

        elif not output_file:
            typer.echo("\n" + "=" * 60)
            typer.echo(result.report_text)
            typer.echo("=" * 60)

    else:
        typer.echo(f"Report generation failed: {result.error}", err=True)

        if error_config.get("enabled", False) and send_email:
            error_recipients: list[str] = error_config.get("recipients", [])
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
                        job_metadata={"run_id": result.run_id},
                    )
                    recipients_str = ", ".join(error_recipients)
                    typer.echo(f"Error notification sent to: {recipients_str}")
                except Exception as exc:
                    typer.echo(f"Failed to send error notification: {exc}", err=True)

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

    Compatibility alias for run --prompt-key spending-report.
    Delegates to AgentRunService with report-specific defaults.

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
