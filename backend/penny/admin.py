"""Admin front door: one-off operator commands (``penny admin ...``).

App code, a front door like ``api/main.py`` / ``cli.py`` — it may construct and
drive the store/services, but is never imported by ``penny/tools`` or the
skills tree and never branches on deployment topology. Today it holds the
one-time ``import-workspace`` migration that lifts a user's local
``~/.transactoid`` into the phase-1b hybrid workspace store.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import uuid

import typer

from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import BlobStore
from penny.workspace_store.broker import ensure_prefixes
from penny.workspace_store.sync import flush, materialize

app = typer.Typer(help="Penny admin/operator commands.", no_args_is_help=True)

# Subdirectories of a legacy ``~/.transactoid`` workspace that carry user state.
_IMPORTED_SUBDIRS = ("memory", "reports")


def import_workspace(
    ctx: RequestContext,
    source_dir: Path,
    *,
    blob_store: BlobStore | None = None,
) -> dict[str, uuid.UUID]:
    """Import ``source_dir/{memory,reports}`` into the user's workspace store.

    Everything imports as **new files**, which route to the user's *private*
    prefix in an individual context — the strict phase-1a default (promote to
    shared later by editing in a shared session). Implemented on the same
    materialize→flush primitives as an agent run: materialize the current
    checkout, copy the legacy files in, flush. Idempotent — a re-run of
    unchanged files produces no new manifest (returns ``{}``).
    """
    from penny.db import get_db
    from penny.workspace_store.blobs import R2BlobStore

    store: BlobStore = blob_store if blob_store is not None else R2BlobStore()
    root = Path(tempfile.mkdtemp(prefix="penny-import-"))
    db = get_db()
    try:
        with db.session_for(ctx) as s:
            ensure_prefixes(s, ctx)
            checkout = materialize(s, ctx, blob_store=store, root=root)
        for sub in _IMPORTED_SUBDIRS:
            src_sub = source_dir / sub
            if not src_sub.is_dir():
                continue
            for f in src_sub.rglob("*"):
                if not f.is_file():
                    continue
                dest = root / f.relative_to(source_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f.read_bytes())
        with db.session_for(ctx) as s:
            return flush(s, ctx, checkout, blob_store=store)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@app.command("import-workspace")
def import_workspace_command(
    household: str = typer.Option(
        ..., "--household", help="Household UUID that owns the imported files."
    ),
    user: str = typer.Option(
        ..., "--user", help="User UUID whose private prefix receives the import."
    ),
    source: Path | None = typer.Option(
        None,
        "--source",
        help="Legacy workspace dir to import (default: the resolved workspace).",
    ),
) -> None:
    """Migrate a local ``~/.transactoid`` workspace into the hybrid store."""
    from penny.bootstrap import bootstrap
    from penny.workspace import resolve_workspace_dir

    bootstrap()
    ctx = RequestContext(user_id=uuid.UUID(user), household_id=uuid.UUID(household))
    heads = import_workspace(ctx, source or resolve_workspace_dir())
    if heads:
        typer.echo(f"Imported {source} — advanced {len(heads)} prefix head(s).")
    else:
        typer.echo(f"Nothing to import from {source} (already up to date).")


def main() -> None:
    """Standalone entry point (also mounted under ``penny admin``)."""
    app()


if __name__ == "__main__":
    main()
