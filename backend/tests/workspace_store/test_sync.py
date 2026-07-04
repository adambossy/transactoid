from pathlib import Path

from penny.adapters.db.models import Household, User, WorkspaceHead, WorkspaceManifest
from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore, content_key
from penny.workspace_store.broker import ensure_prefixes, resolve_readable_prefixes
from penny.workspace_store.sync import materialize


def _seed_with_content(db, blob_store):
    with db.session() as s:
        hh = Household(name="H")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="a@x.com")
        s.add(u)
        s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
        ensure_prefixes(s, ctx)
        infos = resolve_readable_prefixes(s, ctx)
        shared = next(i for i in infos if i.visibility == "shared")
        body = b"# merchant rules\n"
        key = content_key(shared.prefix_token, body)
        blob_store.put(key, body)
        m = WorkspaceManifest(
            prefix_token=shared.prefix_token,
            parent_manifest_id=None,
            entries=[
                {
                    "path": "memory/merchant-rules.md",
                    "sha256": key.split("/", 1)[1],
                    "size": len(body),
                }
            ],
            household_id=ctx.household_id,
            owner_user_id=ctx.user_id,
            visibility="shared",
        )
        s.add(m)
        s.flush()
        s.query(WorkspaceHead).filter_by(prefix_token=shared.prefix_token).update(
            {"head_manifest_id": m.manifest_id}
        )
        return ctx


def test_materialize_writes_head_content(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    f = checkout.root / "memory" / "merchant-rules.md"
    assert f.read_bytes() == b"# merchant rules\n"
    assert checkout.origin["memory/merchant-rules.md"]  # prefix recorded


def test_materialize_empty_head_yields_empty_checkout(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="H")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="a@x.com")
        s.add(u)
        s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
        ensure_prefixes(s, ctx)
        checkout = materialize(
            s, ctx, blob_store=InMemoryBlobStore(), root=tmp_path / "run"
        )
    assert list(checkout.root.rglob("*")) == []
