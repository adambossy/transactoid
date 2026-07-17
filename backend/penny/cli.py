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
from dataclasses import dataclass
from datetime import UTC, datetime
import os

from dotenv import load_dotenv
from loguru import logger
import typer

from penny.observability import init_sentry
from penny.tenancy.context import (
    RequestContext,
    SessionMode,
    cron_principal_from_env,
)

# Load env once at the entrypoint (project convention), without clobbering
# anything deploy already injected into the environment.
load_dotenv(override=False)

# Error tracking as early as possible so CLI / cron-job crashes are reported.
init_sentry()

app = typer.Typer(
    help="Penny — headless personal-finance agent runner.",
    no_args_is_help=True,
)

# Operator commands live in their own front-door module; mount them under
# ``penny admin`` (e.g. ``penny admin import-workspace``).
from penny.admin import app as _admin_app  # noqa: E402

app.add_typer(_admin_app, name="admin")

_DEFAULT_MAX_TURNS = 50


@dataclass(frozen=True, slots=True)
class CronJob:
    """One scheduled agent run with its explicit tenant principal."""

    ctx: RequestContext
    kind: str  # "individual" | "household"


def load_cron_jobs() -> list[CronJob]:
    """Build the scheduled-report jobs from the cron principal env.

    Fails loudly (``RuntimeError``) when either env var is unset — cron never
    runs RLS-unscoped. Yields one ``individual`` job per user id (each scoped to
    that user) plus one ``household`` (joint) job scoped to the whole household.
    """
    household, user_ids = cron_principal_from_env()
    jobs = [
        CronJob(
            ctx=RequestContext(user_id=u, household_id=household), kind="individual"
        )
        for u in user_ids
    ]
    jobs.append(
        CronJob(
            ctx=RequestContext(
                user_id=user_ids[0],
                household_id=household,
                session_mode=SessionMode.JOINT,
            ),
            kind="household",
        )
    )
    return jobs


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


def _build_prompt(*, prompt: str | None, prompt_key: str | None) -> str:
    """Resolve the prompt text to drive the agent with.

    Exactly one of ``prompt`` / ``prompt_key`` is set. A ``prompt_key`` is
    loaded through the shared prompt loader and has its date placeholders
    filled. Recipients are **not** embedded in the prompt: ``send_email_report``
    derives them from the run's ``RequestContext`` (removing the injection
    surface), so the CLI never names an address.
    """
    if prompt_key is not None:
        from penny.prompts import load_prompt

        return _render_template_vars(load_prompt(prompt_key))
    if prompt is not None:
        return prompt
    # callers guarantee exactly one is set; belt-and-suspenders
    raise ValueError("either prompt or prompt_key must be provided")


async def _drive_agent(
    *, prompt_text: str, max_turns: int, ctx: RequestContext
) -> bool:
    """Construct the agent and run it once headlessly. Returns success.

    Uses the identical construction path the web bridge uses
    (``build_agent`` with a fresh ``InMemorySession`` and
    ``persist_session=False``) so cron and chat run the same tools, skills,
    system prompt, and model. No event bus / SSE bridge is needed; the run's
    side effects happen inside the agent's tool calls. The caller supplies an
    explicit ``ctx`` — cron never runs unscoped — which is pinned on the
    ContextVar for the duration of the run and reset after.
    """
    import contextlib
    from pathlib import Path

    from agent_harness.core.events import InMemoryEventBus
    from agent_harness.sessions.inmemory import InMemorySession

    from penny import observability
    from penny.agent_factory import build_agent, build_model
    from penny.tenancy.context import reset_request_context, set_request_context
    from penny.workspace_store.sync import run_with_workspace

    token = set_request_context(ctx)
    session = InMemorySession(session_id=f"cli-{datetime.now(UTC):%Y%m%d%H%M%S}")
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

    async def _run(workspace_dir: Path) -> object:
        # Build the agent rooted at the per-run hybrid checkout so its
        # memory/reports edits land where flush picks them up.
        agent = build_agent(
            model=build_model(),
            session=session,
            persist_session=False,
            ctx=ctx,
            workspace_dir=workspace_dir,
        )
        return await agent.run(prompt_text, event_bus=bus)

    try:
        # materialize the workspace -> run -> flush (aborted run commits nothing).
        result = await run_with_workspace(ctx, _run)
    finally:
        reset_request_context(token)
        if bus is not None:
            await bus.close()
        if trace_task is not None:
            with contextlib.suppress(Exception):
                await trace_task
        # Short-lived process: flush buffered spans before the loop tears down.
        observability.flush()
    return result.output is not None


def _run_and_exit(
    *, prompt_text: str, max_turns: int, ctx: RequestContext | None = None
) -> None:
    """Bootstrap, drive the agent under ``ctx``, and map outcome to exit code.

    When ``ctx`` is None (the default for the manual ``run`` front door), the
    principal comes from the ``PENNY_DEV_*`` env — a missing principal is a
    genuine misconfiguration whose ``ValueError`` propagates to a non-zero exit.
    Callers that already hold an explicit tenant principal (e.g. ``run
    --household`` for the scheduled household report) pass it in directly.
    """
    from penny.bootstrap import bootstrap
    from penny.tenancy.principal import resolve_dev_principal

    bootstrap()
    if ctx is None:
        ctx = resolve_dev_principal({})
    success = asyncio.run(
        _drive_agent(prompt_text=prompt_text, max_turns=max_turns, ctx=ctx)
    )
    if not success:
        typer.echo("Agent run produced no final output", err=True)
        raise typer.Exit(1)
    typer.echo("Agent run completed")


@app.command("run-scheduled-report")
def run_scheduled_report(
    max_turns: int = typer.Option(
        _DEFAULT_MAX_TURNS, "--max-turns", help="Maximum agent turns."
    ),
    individual_only: bool = typer.Option(
        False,
        "--individual-only",
        help=(
            "Emit only the per-user (individual) reports; skip the household "
            "(joint) report. Use when a schedule should reach each user privately "
            "but NOT fan a joint report out to every household member."
        ),
    ),
) -> None:
    """Run today's scheduled reports (New-York-time precedence).

    One report per cron job (``load_cron_jobs``): a personal report scoped to
    each user, plus one household (joint) report. Each runs under its own
    explicit ``RequestContext`` — recipients and data scope both follow from it
    (``send_email_report`` needs no address). Fails loudly if the cron principal
    is unset. Drives the period-parameterized ``spending-report`` skill — there
    are no ``report-*`` prompt keys.

    ``--individual-only`` drops the household (joint) job, so only the per-user
    reports go out (the daily schedule uses this to stay per-user, matching its
    historical single-recipient behavior rather than fanning out to the whole
    household).
    """
    from penny.bootstrap import bootstrap
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

    jobs = load_cron_jobs()  # fails loudly if the cron principal is unset
    if individual_only:
        jobs = [job for job in jobs if job.kind == "individual"]
    bootstrap()
    personal = _build_prompt(prompt=report_prompt(period), prompt_key=None)
    # No dedicated shared-report prompt exists; the household job's JOINT context
    # does the real work (shared-only data + all-member recipients). Reword the
    # possessive so the copy reads as a household report.
    household = personal.replace("my ", "our household's ", 1)

    failures = 0
    for job in jobs:
        prompt_text = household if job.kind == "household" else personal
        ok = asyncio.run(
            _drive_agent(prompt_text=prompt_text, max_turns=max_turns, ctx=job.ctx)
        )
        if not ok:
            failures += 1
            typer.echo(f"Report job failed: {job.kind} {job.ctx.user_id}", err=True)
    if failures:
        raise typer.Exit(1)
    typer.echo(f"Completed {len(jobs)} scheduled report job(s)")


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
    max_turns: int = typer.Option(
        _DEFAULT_MAX_TURNS, "--max-turns", help="Maximum agent turns."
    ),
    household: bool = typer.Option(
        False,
        "--household",
        help=(
            "Run under the cron principal's JOINT household context "
            "(PENNY_CRON_HOUSEHOLD_ID / PENNY_CRON_USER_IDS) instead of the dev "
            "principal, so a report reaches every household member. Used by the "
            "scheduled household report (e.g. the weekly)."
        ),
    ),
) -> None:
    """Run the agent on an explicit prompt or prompt key.

    By default the run uses the dev principal (``PENNY_DEV_*``). ``--household``
    instead pins the cron principal's joint household context, so the recipient
    resolution in ``send_email_report`` reaches every linked household member —
    the recipient still comes from the context, never from the prompt text.
    """
    if prompt is None and prompt_key is None:
        typer.echo("Either --prompt or --prompt-key is required", err=True)
        raise typer.Exit(1)
    if prompt is not None and prompt_key is not None:
        typer.echo("Only one of --prompt or --prompt-key may be provided", err=True)
        raise typer.Exit(1)

    prompt_text = _build_prompt(prompt=prompt, prompt_key=prompt_key)
    ctx: RequestContext | None = None
    if household:
        # The household (JOINT) job carries the shared-data scope + all-member
        # recipient resolution; fails loudly if PENNY_CRON_* is unset.
        ctx = next(job.ctx for job in load_cron_jobs() if job.kind == "household")
    _run_and_exit(prompt_text=prompt_text, max_turns=max_turns, ctx=ctx)


@app.command("sync")
def sync(
    count: int = typer.Option(250, "--count", help="Max transactions per Plaid page."),
) -> None:
    """Sync + categorize the latest transactions for every household.

    Iterates one sync principal per ``(household_id, owner_user_id)`` that has
    connected Plaid items, pinning that tenant ``RequestContext`` before each
    pass so the sync only touches — and stamps its new rows with — that
    principal (the write role bypasses RLS, so scoping is app-level). This is the
    headless peer of the ``sync_transactions`` agent tool, for the cron.

    FUTURE (out of scope, tracked separately): narrow this to *active* households
    only, rather than every household in the database. Two planned activity
    signals:
      1. a user-configurable "jobs" model (regular self-report jobs) — a
         household with an active job counts as active; and
      2. website login recency against a configurable threshold
         (e.g. ``PENNY_ACTIVE_HOUSEHOLD_DAYS`` = 30/90 days).
    A household receiving email reports must count as active even with no login
    or account changes. Until those land, we sync every household.
    """
    from penny.adapters.clients.plaid import PlaidClient
    from penny.bootstrap import bootstrap
    from penny.db import get_db
    import penny.observability as observability
    from penny.services import build_categorizer, get_taxonomy
    from penny.tenancy.context import (
        RequestContext,
        reset_request_context,
        set_request_context,
    )
    from penny.tools._services.sync_service import SyncTool

    bootstrap()
    db = get_db()
    principals = db.list_sync_principals()
    if not principals:
        typer.echo("No households with connected Plaid items — nothing to sync.")
        return

    async def _sync_principal() -> dict[str, object]:
        sync_tool = SyncTool(
            plaid_client=PlaidClient.from_env(),
            categorizer_factory=build_categorizer,
            db=db,
            taxonomy=get_taxonomy(),
        )
        summary = await sync_tool.sync(count=count)
        return summary.to_dict()

    totals = {"added": 0, "modified": 0, "removed": 0}
    failures: list[str] = []
    relink: list[str] = []
    try:
        for household_id, owner_user_id in principals:
            ctx = RequestContext(user_id=owner_user_id, household_id=household_id)
            token = set_request_context(ctx)
            try:
                r = asyncio.run(_sync_principal())
                totals["added"] += int(r.get("total_added") or 0)
                totals["modified"] += int(r.get("total_modified") or 0)
                totals["removed"] += int(r.get("total_removed") or 0)
                relink.extend(r.get("relink_required_items") or [])
                typer.echo(
                    f"  household {household_id} / owner {owner_user_id}: "
                    f"+{r.get('total_added')} ~{r.get('total_modified')} "
                    f"-{r.get('total_removed')}"
                )
            except Exception as exc:  # one principal's failure must not abort the rest
                failures.append(f"{household_id}/{owner_user_id}: {exc}")
                logger.exception(
                    "sync failed for household {} owner {}", household_id, owner_user_id
                )
            finally:
                reset_request_context(token)
    finally:
        # Flush so per-transaction categorizer traces export before we exit.
        observability.flush()

    typer.echo(
        f"Sync complete across {len(principals)} principal(s): "
        f"added={totals['added']} modified={totals['modified']} "
        f"removed={totals['removed']}"
    )
    # A stale bank connection is a user-action item, not a job failure — the sync
    # still ran (other items + categorization). Report it; don't exit non-zero.
    if relink:
        typer.echo(
            f"Connections needing re-authentication: {', '.join(sorted(set(relink)))}"
        )
    if failures:
        typer.echo(f"{len(failures)} principal(s) failed:", err=True)
        for line in failures:
            typer.echo(f"  - {line}", err=True)
        raise typer.Exit(1)


@app.command("eval-categorizer")
def eval_categorizer(
    limit: int = typer.Option(
        None, "--limit", help="Cap the cohort to the most recent N (for testing)."
    ),
    email: list[str] = typer.Option(
        None, "--email", help="Recipient(s) for the per-run status email (repeatable)."
    ),
) -> None:
    """Run one categorizer eval (every 12h schedule).

    Snapshots prod finance data into a local writable SQLite copy (through the
    read-only role, RLS-scoped — no Neon branch, no control-plane credential),
    replays the new agent on the copy, records durable eval rows to prod, uploads
    a SQLite fixture + report to R2, and emails a status line every run (with the
    report link when legacy and agent disagree). Right/wrong is read later from
    your corrections — there is no staging step.
    """
    from penny.eval.job import run_eval
    import penny.observability as observability

    try:
        result = asyncio.run(run_eval(limit=limit, email_to=email or None))
    except Exception as exc:
        typer.echo(f"Eval failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        # Force-flush spans so per-turn traces export before this short-lived
        # process exits (no-op when Langfuse is disabled).
        observability.flush()
    typer.echo(f"Eval {result.get('status')}: {result}")


@app.command("reap-sandboxes")
def reap_sandboxes() -> None:
    """Terminate idle per-conversation Modal sandboxes (Fly-cron sweep).

    Stateless + durable: the live boxes come from Modal (each tagged with its
    conversation_id), the idle clock from the persisted transcript — so it needs
    no in-memory registry and survives a Fly restart. A box is spared while its
    conversation's turn is in flight (trailing user message). See
    ``penny.sandboxes.reaper.reap_idle_sandboxes``.
    """
    import time

    from penny.api.persistence.store import ConversationStore
    from penny.sandboxes.provider import ModalSandboxProvider
    from penny.sandboxes.reaper import reap_idle_sandboxes

    app_name = os.environ.get("PENNY_SANDBOX_APP", "penny-sandbox")
    # The image ref is unused for reaping (list + terminate only).
    provider = ModalSandboxProvider(app_name, os.environ.get("PENNY_SANDBOX_IMAGE", ""))
    store = ConversationStore()

    try:
        reaped = asyncio.run(
            reap_idle_sandboxes(provider, store.latest_activity, now=time.time())
        )
    except Exception as exc:
        typer.echo(f"Reap failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Reaped {len(reaped)} idle sandbox(es): {', '.join(reaped) or '(none)'}"
    )


@app.command("migrate")
def migrate_cmd() -> None:
    """Apply alembic migrations to head — the prod release step.

    Deploy runs this via the Fly ``release_command`` (see deploy/backend/
    fly.toml), once in an ephemeral machine before the app machines start.
    Idempotent; non-zero exit on failure fails the deploy.
    """
    from penny.schema import upgrade_to_head

    upgrade_to_head()  # env.py reads DATABASE_URL
    logger.info("penny migrate: schema at head")


def main() -> None:
    """Console-script entry point (``[project.scripts] penny``)."""
    app()


if __name__ == "__main__":
    main()
