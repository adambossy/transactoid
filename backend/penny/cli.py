"""Headless Typer CLI — a peer front door beside ``penny.api.main``.

This is the entry point the cron-manager invokes (``penny
run-scheduled-report`` / ``penny run --prompt-key … --email …``). It drives
the same agent the web bridge drives, minus the SSE translation: there is no
HTTP request, no chat UI, and no browser. The report's side effects (R2
upload, email send) happen inside the agent's own tool calls exactly as in an
interactive run, so the CLI never re-implements report logic — it only
constructs the agent and runs it with the right prompt.

Segregation: this is *app code*, a front door (like ``api/main.py``), not
*deploy code* and not *agent-internal*. It may construct and drive the agent
(``agent_factory``, ``bootstrap``, the services); it must never be imported by
``penny/tools`` or the skills tree, and it never reads a ``fly.toml`` or
branches on deployment topology. The only seam with deploy is the ``PENNY_*``
env contract that ``config.py``/``os.environ`` read.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from dotenv import load_dotenv
from loguru import logger
import typer

# Load env once at the entrypoint (project convention), without clobbering
# anything deploy already injected into the environment.
load_dotenv(override=False)

app = typer.Typer(
    help="Penny — headless personal-finance agent runner.",
    no_args_is_help=True,
)

_DEFAULT_MAX_TURNS = 50


def _render_template_vars(text: str) -> str:
    """Fill the per-run date placeholders a report prompt may carry.

    Mirrors the legacy CLI's default template vars (``CURRENT_DATE`` /
    ``CURRENT_MONTH`` / ``CURRENT_YEAR``) so a prompt that says "for the week
    ending {{CURRENT_DATE}}" resolves to today's date.
    """
    now = datetime.now(UTC)
    replacements = {
        "{{CURRENT_DATE}}": now.strftime("%Y-%m-%d"),
        "{{CURRENT_MONTH}}": now.strftime("%B"),
        "{{CURRENT_YEAR}}": now.strftime("%Y"),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _build_prompt(
    *, prompt: str | None, prompt_key: str | None, email: list[str]
) -> str:
    """Resolve the prompt text to drive the agent with.

    Exactly one of ``prompt`` / ``prompt_key`` is set. A ``prompt_key`` is
    loaded through the shared prompt loader and has its date placeholders
    filled. When ``--email`` recipients are supplied, a delivery instruction
    is appended so the agent emails the finished report itself (delivery stays
    agent-driven — the CLI never touches the email/R2 services directly).
    """
    if prompt_key is not None:
        from penny.prompts import load_prompt

        body = _render_template_vars(load_prompt(prompt_key))
    elif prompt is not None:
        body = prompt
    else:  # callers guarantee exactly one is set; belt-and-suspenders
        raise ValueError("either prompt or prompt_key must be provided")

    if email:
        recipients = ", ".join(email)
        body = (
            f"{body}\n\nWhen the report is complete, email it to the following "
            f"recipient(s): {recipients}."
        )
    return body


async def _drive_agent(*, prompt_text: str, max_turns: int) -> bool:
    """Construct the agent and run it once headlessly. Returns success.

    Uses the identical construction path the web bridge uses
    (``build_agent`` with a fresh ``InMemorySession`` and
    ``persist_session=False``) so cron and chat run the same tools, skills,
    system prompt, and model. No event bus / SSE bridge is needed; the run's
    side effects happen inside the agent's tool calls.
    """
    import contextlib

    from agent_harness.core.events import InMemoryEventBus
    from agent_harness.sessions.inmemory import InMemorySession

    from penny import observability
    from penny.agent_factory import build_agent, build_model

    session = InMemorySession(session_id=f"cli-{datetime.now(UTC):%Y%m%d%H%M%S}")
    agent = build_agent(model=build_model(), session=session, persist_session=False)
    # max_turns is accepted for parity with the legacy CLI surface and the
    # cron command line; the harness loop is currently bounded by the model
    # producing a final output. Logged so the value is visible in cron logs.
    logger.bind(max_turns=max_turns).info("Driving headless agent run")

    # Only stand up an EventBus when Langfuse is on — chat uses one for the SSE
    # bridge, but cron has no other consumer, so keep the no-trace path bus-free.
    bus = InMemoryEventBus() if observability.is_enabled() else None
    trace_task = observability.start_run_trace_task(
        bus, source="cron", session_id=session.session_id, prompt=prompt_text
    )
    try:
        result = await agent.run(prompt_text, event_bus=bus)
    finally:
        if bus is not None:
            await bus.close()
        if trace_task is not None:
            with contextlib.suppress(Exception):
                await trace_task
        # Short-lived process: flush buffered spans before the loop tears down.
        observability.flush()
    return result.output is not None


def _run_and_exit(*, prompt_text: str, max_turns: int) -> None:
    """Bootstrap, drive the agent, and map the outcome to an exit code."""
    from penny.bootstrap import bootstrap

    bootstrap()
    success = asyncio.run(_drive_agent(prompt_text=prompt_text, max_turns=max_turns))
    if not success:
        typer.echo("Agent run produced no final output", err=True)
        raise typer.Exit(1)
    typer.echo("Agent run completed")


@app.command("run-scheduled-report")
def run_scheduled_report(
    email: list[str] = typer.Option(
        None,
        "--email",
        help="Email recipient(s) for the report (repeatable).",
    ),
    max_turns: int = typer.Option(
        _DEFAULT_MAX_TURNS, "--max-turns", help="Maximum agent turns."
    ),
) -> None:
    """Run today's scheduled report (New-York-time precedence).

    Drives the period-parameterized ``spending-report`` skill — there are no
    ``report-*`` prompt keys; the period is turned into a skill-triggering
    request via ``report_prompt``.
    """
    from penny.services.scheduled_reports import (
        NEW_YORK_TZ,
        report_prompt,
        select_report_period,
    )

    now_utc = datetime.now(UTC)
    now_ny = now_utc.astimezone(NEW_YORK_TZ)
    period = select_report_period(now_utc=now_utc)
    typer.echo(
        f"Selected scheduled report period: {period} ({now_ny:%Y-%m-%d %H:%M:%S %Z})"
    )
    prompt_text = _build_prompt(
        prompt=report_prompt(period), prompt_key=None, email=email or []
    )
    _run_and_exit(prompt_text=prompt_text, max_turns=max_turns)


@app.command("run")
def run(
    prompt: str = typer.Option(
        None, "--prompt", help="Raw prompt text to send to the agent."
    ),
    prompt_key: str = typer.Option(
        None,
        "--prompt-key",
        help="Promptorium key to load (e.g. 'report-weekly-jenny').",
    ),
    email: list[str] = typer.Option(
        None, "--email", help="Email recipient(s) for the report (repeatable)."
    ),
    max_turns: int = typer.Option(
        _DEFAULT_MAX_TURNS, "--max-turns", help="Maximum agent turns."
    ),
) -> None:
    """Run the agent on an explicit prompt or prompt key."""
    if prompt is None and prompt_key is None:
        typer.echo("Either --prompt or --prompt-key is required", err=True)
        raise typer.Exit(1)
    if prompt is not None and prompt_key is not None:
        typer.echo("Only one of --prompt or --prompt-key may be provided", err=True)
        raise typer.Exit(1)

    prompt_text = _build_prompt(prompt=prompt, prompt_key=prompt_key, email=email or [])
    _run_and_exit(prompt_text=prompt_text, max_turns=max_turns)


@app.command("sync")
def sync(
    count: int = typer.Option(250, "--count", help="Max transactions per Plaid page."),
) -> None:
    """Sync + categorize the latest transactions from every Plaid item.

    Headless wrapper over the same ``SyncTool`` the ``sync_transactions``
    agent tool calls — for any schedule that wants a fresh pull before
    reporting.
    """
    from penny.adapters.clients.plaid import PlaidClient
    from penny.bootstrap import bootstrap
    from penny.db import get_db
    from penny.services import build_categorizer, get_taxonomy
    from penny.tools._services.sync_service import SyncTool

    bootstrap()

    async def _sync() -> dict[str, object]:
        sync_tool = SyncTool(
            plaid_client=PlaidClient.from_env(),
            categorizer_factory=build_categorizer,
            db=get_db(),
            taxonomy=get_taxonomy(),
        )
        summary = await sync_tool.sync(count=count)
        return summary.to_dict()

    try:
        result = asyncio.run(_sync())
    except Exception as exc:
        typer.echo(f"Sync failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        "Sync complete: "
        f"added={result.get('total_added')} "
        f"modified={result.get('total_modified')} "
        f"removed={result.get('total_removed')}"
    )


@app.command("eval-categorizer")
def eval_categorizer(
    limit: int = typer.Option(
        None, "--limit", help="Cap the cohort to the most recent N (for testing)."
    ),
    email: list[str] = typer.Option(
        None, "--email", help="Recipient(s) for disagreement reports (repeatable)."
    ),
) -> None:
    """Run one categorizer eval (every 12h schedule).

    Branches off the Neon production branch, replays the new agent on the branch,
    records durable eval rows to prod, dumps the branch to a SQLite fixture in R2,
    deletes the branch, and emails the report only when legacy and agent disagree.
    Right/wrong is read later from your corrections — there is no staging step.
    """
    from penny.eval.job import run_eval

    try:
        result = asyncio.run(run_eval(limit=limit, email_to=email or None))
    except Exception as exc:
        typer.echo(f"Eval failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Eval {result.get('status')}: {result}")


def main() -> None:
    """Console-script entry point (``[project.scripts] penny``)."""
    app()


if __name__ == "__main__":
    main()
