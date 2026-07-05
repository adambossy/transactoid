"""Stage 0 — the frozen Neon restore branch.

Creates a Neon branch off the prod branch as the untouched restore point (step 0
of the safety order). Idempotent: once a frozen branch is recorded in the state
file it refuses to make another and just reprints the restore command.

This module SHAPES and runs the ``neonctl`` command at the operator's request;
the build phase never invokes it (``--dry-run`` prints the exact command).
"""

from __future__ import annotations

from datetime import datetime, timezone
import shutil
import subprocess

from common import CutoverState, echo, require

STAGE = "backup"


def run(
    *,
    project_id: str | None,
    parent_branch: str,
    branch_name: str | None,
    state_file: str,
    dry_run: bool,
) -> None:
    state = CutoverState.load(state_file)

    existing = state.get("backup_branch")
    if existing:
        # Idempotent: a frozen branch already exists for this run. Never make a
        # second restore point — reprint how to restore from the first.
        echo(f"Frozen backup branch already recorded: {existing}")
        _print_restore(project_id, parent_branch, existing)
        return

    name = branch_name or f"penny-cutover-frozen-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    cmd = ["neonctl", "branches", "create", "--name", name, "--parent", parent_branch]
    if project_id:
        cmd += ["--project-id", project_id]

    if dry_run:
        echo("[dry-run] would create the frozen restore branch:")
        echo("  " + " ".join(cmd))
        echo("[dry-run] restore path after creation:")
        _print_restore(project_id, parent_branch, name)
        return

    require(shutil.which("neonctl") is not None, "neonctl not found on PATH")
    echo(f"Creating frozen restore branch {name!r} off {parent_branch!r} ...")
    subprocess.run(cmd, check=True)

    state.set("backup_branch", name)
    state.set("backup_parent", parent_branch)
    state.mark_done(STAGE)
    echo(f"Recorded frozen branch {name!r} in {state_file}. DO NOT touch it until verify passes.")
    _print_restore(project_id, parent_branch, name)


def _print_restore(project_id: str | None, parent_branch: str, frozen: str) -> None:
    """Print the command that restores prod from the frozen branch if the apply
    goes wrong. ``neonctl branches restore`` overwrites the target with a source
    branch's state."""
    proj = f" --project-id {project_id}" if project_id else ""
    echo("Restore path (only if the prod apply goes wrong):")
    echo(f"  neonctl branches restore {parent_branch} {frozen}{proj}")
    echo(f"  # overwrites {parent_branch!r} with the frozen {frozen!r} snapshot")
