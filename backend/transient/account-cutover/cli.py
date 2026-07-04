#!/usr/bin/env python
"""``penny-cutover`` — the phase-3 production-cutover CLI (TRANSIENT / one-off).

Ordered, idempotent, resumable stages that move the existing single-user prod
data into the multi-tenant world. Each stage is ``--dry-run``-able and records
progress in ``.cutover-state.json`` so a re-run resumes rather than repeats.

Run order (see README for the full safety runbook):

    backup -> reconcile-expand -> bootstrap -> assign-accounts
           -> reparent -> finalize-schema -> verify

Invoke from ``backend/`` so the canonical ``penny`` package imports resolve::

    DATABASE_URL=<rehearsal-branch-url> \\
        uv run python transient/account-cutover/cli.py <stage> [--dry-run] ...

NON-CANONICAL (AGENTS.md): not imported by app code, exempt from the lint/test
gate, deletable after the cutover.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# The dir is not an importable package (it has a hyphen); put it on the path so
# ``common`` and ``stages.*`` resolve regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import typer  # noqa: E402

from stages import (  # noqa: E402
    assign,
    backup,
    bootstrap,
    finalize,
    reconcile,
    reparent,
    verify,
)

app = typer.Typer(
    add_completion=False,
    help="Phase-3 production cutover (transient one-off tool).",
    no_args_is_help=True,
)

DEFAULT_STATE = ".cutover-state.json"
DEFAULT_MAPPING = "accounts.mapping.yaml"


@app.command("backup")
def backup_cmd(
    project_id: str = typer.Option(
        None, "--project-id", envvar="NEON_PROJECT_ID", help="Neon project id."
    ),
    parent_branch: str = typer.Option(
        ..., "--parent-branch", help="Branch to snapshot (the PROD branch)."
    ),
    branch_name: str = typer.Option(
        None, "--branch-name", help="Name for the frozen restore branch (auto if omitted)."
    ),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Step 0: create the FROZEN Neon restore branch (untouched until verify)."""
    backup.run(
        project_id=project_id,
        parent_branch=parent_branch,
        branch_name=branch_name,
        state_file=state_file,
        dry_run=dry_run,
    )


@app.command("reconcile-expand")
def reconcile_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    stamp_baseline: str = typer.Option(
        None, "--stamp-baseline", help="Revision to stamp as the applied baseline."
    ),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Reconcile prod's alembic baseline + apply the EXPAND half (010-013)."""
    reconcile.run(
        db_url=db_url,
        stamp_baseline=stamp_baseline,
        state_file=state_file,
        dry_run=dry_run,
    )


@app.command("bootstrap")
def bootstrap_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    household_name: str = typer.Option(..., "--household-name"),
    email: list[str] = typer.Option(
        ..., "--email", help="Pending user email (pass twice: you + your spouse)."
    ),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Create the household + two PENDING users (external_auth_id NULL)."""
    bootstrap.run(
        db_url=db_url,
        household_name=household_name,
        emails=email,
        state_file=state_file,
        dry_run=dry_run,
    )


@app.command("assign-accounts")
def assign_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    mapping: str = typer.Option(DEFAULT_MAPPING, "--mapping"),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Interactively assign each linked account's owner + visibility."""
    assign.run(
        db_url=db_url,
        mapping_file=mapping,
        state_file=state_file,
        dry_run=dry_run,
    )


@app.command("reparent")
def reparent_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    mapping: str = typer.Option(DEFAULT_MAPPING, "--mapping"),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Apply the mapping, denormalize onto children, assert zero unassigned."""
    reparent.run(
        db_url=db_url,
        mapping_file=mapping,
        state_file=state_file,
        dry_run=dry_run,
    )


@app.command("finalize-schema")
def finalize_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Apply the CONTRACT half (014-head) now that every row is assigned."""
    finalize.run(db_url=db_url, state_file=state_file, dry_run=dry_run)


@app.command("verify")
def verify_cmd(
    db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
    app_db_url: str = typer.Option(
        None,
        "--app-db-url",
        help="Non-superuser role URL for the RLS isolation checks (defaults to --db-url).",
    ),
    state_file: str = typer.Option(DEFAULT_STATE, "--state-file"),
) -> None:
    """Isolation/privacy checks on the migrated data (gates backup release)."""
    verify.run(db_url=db_url, app_db_url=app_db_url, state_file=state_file)


def main() -> None:
    # A friendly nudge if run from the wrong cwd (penny imports need backend/).
    if not os.path.exists("alembic.ini") and "--help" not in sys.argv:
        print(
            "warning: run from backend/ so `penny` imports resolve "
            "(cwd has no alembic.ini).",
            file=sys.stderr,
        )
    app()


if __name__ == "__main__":
    main()
