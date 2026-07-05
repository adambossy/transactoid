"""Postgres RLS isolation for the workspace store — runs only when
POSTGRES_TEST_URL is set.

The workspace tables carry the same household/owner/visibility triple as the
financial tables and get the identical ``tenant_isolation`` policy (USING **and**
WITH CHECK, FORCE RLS). This battery proves a household can't see another's
prefixes/manifests, a spouse's private prefix is hidden, a joint session
resolves shared-only, joint materialize never touches private bytes, and a
cross-household insert is rejected by WITH CHECK. Mirrors the seed shape of
``test_rls_isolation.py``.
"""

from pathlib import Path
import shutil
import tempfile
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.models import Household, User
from penny.tenancy.context import RequestContext, SessionMode
from penny.workspace_store.blobs import InMemoryBlobStore
from penny.workspace_store.broker import (
    ensure_prefixes,
    resolve_readable_prefixes,
)
from penny.workspace_store.sync import flush, materialize

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
UA1, UA2 = uuid.uuid4(), uuid.uuid4()  # two users in household A
UB1 = uuid.uuid4()  # one user in household B


def _ctx(
    user: uuid.UUID, household: uuid.UUID, *, joint: bool = False
) -> RequestContext:
    mode = SessionMode.JOINT if joint else SessionMode.INDIVIDUAL
    return RequestContext(user_id=user, household_id=household, session_mode=mode)


def _seed_identity(db) -> None:
    with db.session() as s:  # identity tables carry no RLS
        s.add_all(
            [Household(household_id=HA, name="A"), Household(household_id=HB, name="B")]
        )
        s.flush()
        s.add_all(
            [
                User(user_id=UA1, household_id=HA, email=f"{UA1}@x.com"),
                User(user_id=UA2, household_id=HA, email=f"{UA2}@x.com"),
                User(user_id=UB1, household_id=HB, email=f"{UB1}@x.com"),
            ]
        )


def _write(
    db, ctx: RequestContext, blobs: InMemoryBlobStore, path: str, body: bytes
) -> None:
    """Materialize under ``ctx``, drop a file, flush — creating content in the
    prefix that file routes to (private in individual mode, shared in joint)."""
    root = Path(tempfile.mkdtemp(prefix="penny-rls-"))
    try:
        with db.session_for(ctx) as s:
            ensure_prefixes(s, ctx)
            checkout = materialize(s, ctx, blob_store=blobs, root=root)
        dest = checkout.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        with db.session_for(ctx) as s:
            flush(s, ctx, checkout, blob_store=blobs)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _seed_prefixes(db) -> InMemoryBlobStore:
    _seed_identity(db)
    blobs = InMemoryBlobStore()
    # Private content for each of A's users, a shared file for A, and B's data.
    _write(db, _ctx(UA1, HA), blobs, "memory/private-a1.md", b"a1 secret\n")
    _write(db, _ctx(UA2, HA), blobs, "memory/private-a2.md", b"a2 secret\n")
    _write(db, _ctx(UA1, HA, joint=True), blobs, "memory/shared-a.md", b"a shared\n")
    _write(db, _ctx(UB1, HB), blobs, "memory/private-b1.md", b"b1 secret\n")
    return blobs


def test_cross_household_prefixes_invisible(pg_db):
    _seed_prefixes(pg_db)
    with pg_db.session_for(_ctx(UA1, HA)) as s:
        rows = s.execute(sa.text("SELECT household_id FROM workspace_prefixes")).all()
    # Every visible prefix belongs to A; not one of B's rows leaks through.
    assert rows and all(r[0] == HA for r in rows)


def test_spouse_private_prefix_invisible(pg_db):
    _seed_prefixes(pg_db)
    with pg_db.session_for(_ctx(UA1, HA)) as s:
        prefixes = s.execute(
            sa.text(
                "SELECT owner_user_id, visibility FROM workspace_prefixes "
                "WHERE visibility = 'private'"
            )
        ).all()
        manifests = s.execute(
            sa.text(
                "SELECT owner_user_id FROM workspace_manifests "
                "WHERE visibility = 'private'"
            )
        ).all()
    # UA1 sees only its own private prefix/manifest — never UA2's.
    assert all(r[0] == UA1 for r in prefixes)
    assert all(r[0] == UA1 for r in manifests)


def test_joint_ctx_cannot_select_private_rows(pg_db):
    _seed_prefixes(pg_db)
    with pg_db.session_for(_ctx(UA1, HA, joint=True)) as s:
        rows = s.execute(sa.text("SELECT visibility FROM workspace_prefixes")).all()
    # Joint session's effective user is the nil sentinel: shared rows only.
    assert rows and all(r[0] == "shared" for r in rows)


def test_joint_materialize_never_touches_private(pg_db):
    blobs = _seed_prefixes(pg_db)
    joint = _ctx(UA1, HA, joint=True)
    root = Path(tempfile.mkdtemp(prefix="penny-rls-joint-"))
    try:
        with pg_db.session_for(joint) as s:
            infos = resolve_readable_prefixes(s, joint)
            checkout = materialize(s, joint, blob_store=blobs, root=root)
        # Only the shared prefix is ever resolved; no private file materialized.
        assert all(i.visibility == "shared" for i in infos)
        assert all(not p.startswith("memory/private") for p in checkout.origin)
        materialized = {
            str(f.relative_to(root)) for f in root.rglob("*") if f.is_file()
        }
        assert not any(name.startswith("memory/private") for name in materialized)
        assert "memory/shared-a.md" in materialized
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_with_check_blocks_foreign_household_insert(pg_db):
    _seed_prefixes(pg_db)
    from penny.adapters.db.models import WorkspacePrefix

    with pytest.raises(sa.exc.DBAPIError):  # WITH CHECK violation
        with pg_db.session_for(_ctx(UA1, HA)) as s:
            s.add(
                WorkspacePrefix(
                    prefix_token="evil-cross-household",
                    household_id=HB,  # not A's household
                    owner_user_id=UB1,
                    visibility="private",
                    kind="private",
                )
            )
            s.flush()
