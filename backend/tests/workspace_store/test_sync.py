import hashlib
from pathlib import Path

from penny.adapters.db.models import Household, User, WorkspaceHead, WorkspaceManifest
from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore, content_key
from penny.workspace_store.broker import ensure_prefixes, resolve_readable_prefixes
from penny.workspace_store.sync import flush, materialize


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
        key = content_key(shared.prefix_token, hashlib.sha256(body).hexdigest())
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


def test_flush_commits_changed_and_new_files(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    (checkout.root / "memory" / "merchant-rules.md").write_bytes(b"# updated\n")
    (checkout.root / "memory" / "new-note.md").write_bytes(b"note\n")
    with db.session() as s:
        heads = flush(s, ctx, checkout, blob_store=blobs)
    assert len(heads) >= 1
    with db.session() as s:
        again = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run2")
    assert (again.root / "memory" / "merchant-rules.md").read_bytes() == b"# updated\n"
    assert (again.root / "memory" / "new-note.md").read_bytes() == b"note\n"


def test_new_file_in_individual_mode_lands_in_private_prefix(
    isolated_db, tmp_path: Path
):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    (checkout.root / "memory" / "private-note.md").write_bytes(b"secret\n")
    with db.session() as s:
        flush(s, ctx, checkout, blob_store=blobs)
    private = next(i for i in checkout.prefixes if i.visibility == "private")
    with db.session() as s:
        from penny.workspace_store.sync import _head_snapshot

        snap = _head_snapshot(s, private.prefix_token)
    assert "memory/private-note.md" in snap.entries


def test_nothing_changed_no_new_manifest(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    with db.session() as s:
        assert flush(s, ctx, checkout, blob_store=blobs) == {}


def test_concurrent_flush_retries_and_preserves_both_edits(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        c1 = materialize(s, ctx, blob_store=blobs, root=tmp_path / "r1")
    with db.session() as s:
        c2 = materialize(s, ctx, blob_store=blobs, root=tmp_path / "r2")
    (c1.root / "memory" / "from-run1.md").write_bytes(b"one\n")
    (c2.root / "memory" / "from-run2.md").write_bytes(b"two\n")
    with db.session() as s:
        flush(s, ctx, c1, blob_store=blobs)
    with db.session() as s:
        flush(s, ctx, c2, blob_store=blobs)  # CAS conflict -> retry path
    with db.session() as s:
        final = materialize(s, ctx, blob_store=blobs, root=tmp_path / "r3")
    assert (final.root / "memory" / "from-run1.md").exists()
    assert (final.root / "memory" / "from-run2.md").exists()
