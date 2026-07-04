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

from dataclasses import dataclass, field
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from penny.adapters.db.models import WorkspaceHead, WorkspaceManifest
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import BlobStore
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
            target.write_bytes(blob_store.get(f"{info.prefix_token}/{sha}"))
            checkout.origin[path] = info.prefix_token
    return checkout
