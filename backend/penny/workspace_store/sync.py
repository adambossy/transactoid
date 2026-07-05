"""Materialize / flush: the git-like checkout ⇄ commit layer.

*Temp dir = working tree, R2 = object store, Postgres manifest = the commit.*
:func:`materialize` reads each readable prefix's head manifest into a per-run
temp checkout (shared first, private overlaid). :func:`flush` diffs the
checkout against the baselines, uploads changed blobs (content-addressed,
immutable, pre-CAS), and advances each touched prefix's head with a single
compare-and-set — atomic and lost-update-safe. An aborted run never calls
flush, so nothing is committed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import shutil
import tempfile
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from penny.adapters.db.models import WorkspaceHead, WorkspaceManifest
from penny.tenancy.context import RequestContext, SessionMode
from penny.workspace_store.blobs import BlobStore, content_key
from penny.workspace_store.broker import PrefixInfo, resolve_readable_prefixes


@dataclass(slots=True)
class ManifestSnapshot:
    manifest_id: uuid.UUID | None
    entries: dict[str, str]  # path -> sha256


@dataclass(slots=True)
class WorkspaceCheckout:
    root: Path
    prefixes: list[PrefixInfo]
    baselines: dict[str, ManifestSnapshot] = field(default_factory=dict)  # by token
    origin: dict[str, str] = field(default_factory=dict)  # path -> prefix_token


def _head_snapshot(session: Session, prefix_token: str) -> ManifestSnapshot:
    head = session.query(WorkspaceHead).filter_by(prefix_token=prefix_token).one()
    if head.head_manifest_id is None:
        return ManifestSnapshot(manifest_id=None, entries={})
    manifest = (
        session.query(WorkspaceManifest)
        .filter_by(manifest_id=head.head_manifest_id)
        .one()
    )
    return ManifestSnapshot(
        manifest_id=manifest.manifest_id,
        entries={e["path"]: e["sha256"] for e in manifest.entries},
    )


def materialize(
    session: Session, ctx: RequestContext, *, blob_store: BlobStore, root: Path
) -> WorkspaceCheckout:
    """Read the readable prefixes' heads into a fresh checkout under ``root``.

    Broker order (shared first, private overlaying) means a user's private
    edit wins a path collision in their own session. Records each path's
    origin prefix so flush can route the write-back to the right visibility.
    """
    root.mkdir(parents=True, exist_ok=True)
    prefixes = resolve_readable_prefixes(session, ctx)
    checkout = WorkspaceCheckout(root=root, prefixes=prefixes)
    for info in prefixes:  # shared first; private overlays on path collision
        snap = _head_snapshot(session, info.prefix_token)
        checkout.baselines[info.prefix_token] = snap
        for path, sha in snap.entries.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob_store.get(content_key(info.prefix_token, sha)))
            checkout.origin[path] = info.prefix_token
    return checkout


class FlushConflictError(Exception):
    """CAS kept failing after retries — the head moved faster than we could
    re-apply."""


def _route_new_path(checkout: WorkspaceCheckout, ctx: RequestContext) -> str:
    """Which prefix a brand-new file belongs to.

    Individual mode → the private prefix (promotable to shared later); joint
    mode → the shared prefix (the only scope a joint run ever holds, so
    private data can't leak outward even on write).
    """
    want = "private" if ctx.session_mode is SessionMode.INDIVIDUAL else "shared"
    for info in checkout.prefixes:
        if info.visibility == want:
            return info.prefix_token
    return checkout.prefixes[0].prefix_token  # joint: shared is the only prefix


def _cas_advance_head(
    session: Session,
    token: str,
    *,
    new_manifest_id: uuid.UUID,
    parent_manifest_id: uuid.UUID | None,
) -> int:
    """Advance a prefix head iff it still equals the parent we branched from.

    A single conditional UPDATE — the only mutating step of a commit, so the
    flush is atomic. Uses ORM column typing (not raw SQL) so the UUID binds
    correctly on both SQLite (CHAR(32)) and Postgres (native uuid). Returns
    the affected row count (1 = won, 0 = the head moved).
    """
    stmt = update(WorkspaceHead).where(WorkspaceHead.prefix_token == token)
    if parent_manifest_id is None:
        stmt = stmt.where(WorkspaceHead.head_manifest_id.is_(None))
    else:
        stmt = stmt.where(WorkspaceHead.head_manifest_id == parent_manifest_id)
    stmt = stmt.values(head_manifest_id=new_manifest_id)
    return session.execute(stmt).rowcount


def flush(
    session: Session,
    ctx: RequestContext,
    checkout: WorkspaceCheckout,
    *,
    blob_store: BlobStore,
    max_retries: int = 3,
) -> dict[str, uuid.UUID]:
    """Commit the checkout: diff, upload changed blobs, CAS each touched head.

    Returns the new head manifest id per touched prefix token (empty dict when
    nothing changed — no empty commit). New files are visibility-routed
    (:func:`_route_new_path`); a changed existing file flushes back to the
    prefix it came from (``checkout.origin``), so a joint run can only write
    shared. On CAS conflict the head is re-materialized and this run's changes
    re-applied per-file (last-writer-wins), retried up to ``max_retries``.
    """
    # 1. Current working-tree state.
    current: dict[str, bytes] = {}
    for f in checkout.root.rglob("*"):
        if f.is_file():
            current[str(f.relative_to(checkout.root))] = f.read_bytes()

    # 2. Per-prefix change sets (path -> bytes, or None for a delete).
    changes: dict[str, dict[str, bytes | None]] = {}
    baseline_union = {
        path: (token, sha)
        for token, snap in checkout.baselines.items()
        for path, sha in snap.entries.items()
    }
    for path, body in current.items():
        sha = hashlib.sha256(body).hexdigest()
        known = baseline_union.get(path)
        if known is None:
            changes.setdefault(_route_new_path(checkout, ctx), {})[path] = body
        elif known[1] != sha:
            changes.setdefault(checkout.origin[path], {})[path] = body
    for path, (token, _sha) in baseline_union.items():
        if path not in current:
            changes.setdefault(token, {})[path] = None  # deleted

    new_heads: dict[str, uuid.UUID] = {}
    for token, delta in changes.items():
        info = next(i for i in checkout.prefixes if i.prefix_token == token)
        parent = checkout.baselines.get(token, ManifestSnapshot(None, {}))
        for _attempt in range(max_retries + 1):
            entries = dict(parent.entries)
            for path, body in delta.items():
                if body is None:
                    entries.pop(path, None)
                    continue
                sha = hashlib.sha256(body).hexdigest()
                key = content_key(token, sha)
                if not blob_store.exists(key):
                    blob_store.put(key, body)  # immutable, pre-CAS, safe
                entries[path] = sha
            manifest = WorkspaceManifest(
                prefix_token=token,
                parent_manifest_id=parent.manifest_id,
                entries=[
                    {"path": p, "sha256": s, "size": 0} for p, s in entries.items()
                ],
                household_id=ctx.household_id,
                owner_user_id=info.owner_user_id,
                visibility=info.visibility,
            )
            session.add(manifest)
            session.flush()
            if _cas_advance_head(
                session,
                token,
                new_manifest_id=manifest.manifest_id,
                parent_manifest_id=parent.manifest_id,
            ):
                new_heads[token] = manifest.manifest_id
                break
            # Conflict: the head moved. Adopt it as the new parent (its entries
            # become the base) and re-apply this run's delta, then retry.
            session.expire_all()
            parent = _head_snapshot(session, token)
        else:
            raise FlushConflictError(f"prefix {token} kept moving")
    return new_heads


async def run_with_workspace[T](
    ctx: RequestContext,
    run_fn: Callable[[Path], Awaitable[T]],
    *,
    blob_store: BlobStore | None = None,
) -> T:
    """materialize → ``await run_fn(checkout_root)`` → flush; abort → no flush.

    The lifecycle wrapper every front door drives an agent through: a per-run
    temp checkout under the scratch area is materialized from the store, handed
    to ``run_fn`` to edit freely at local-FS speed, then flushed back on
    success. The temp dir is always removed. An exception from ``run_fn``
    propagates before flush, so an aborted run commits nothing. ``blob_store``
    defaults to R2 in production; tests inject the in-memory fake.
    """
    from penny.db import get_db
    from penny.workspace_store.blobs import R2BlobStore
    from penny.workspace_store.broker import ensure_prefixes

    store: BlobStore = blob_store if blob_store is not None else R2BlobStore()
    root = Path(tempfile.mkdtemp(prefix="penny-ws-"))
    db = get_db()
    try:
        with db.session_for(ctx) as s:
            ensure_prefixes(s, ctx)
            checkout = materialize(s, ctx, blob_store=store, root=root)
        result = await run_fn(checkout.root)
        with db.session_for(ctx) as s:
            flush(s, ctx, checkout, blob_store=store)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)
