# Phase 1b — Workspace Hybrid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [foundation design — Workspace section](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 1a plan](2026-06-27-phase-1a-multi-tenant-data-model.md) ·
> **Next:** [Phase 2 plan](2026-07-02-phase-2-auth-social-login.md)

**Goal:** Move the per-household workspace (memory, merchant rules, reports) off
the local filesystem onto the hybrid store — Postgres+RLS as capability broker,
R2 as blob store — with manifest versioning and atomic compare-and-set
write-back.

**Architecture:** Three new RLS-protected tables (`workspace_prefixes`,
`workspace_manifests`, `workspace_heads`) broker access to content-addressed
blobs in R2 (`{prefix_token}/{sha256}`). A run materializes its readable
prefixes into a per-run temp checkout, the agent edits locally, and a flush
uploads changed blobs then advances each prefix's head with a single
compare-and-set. Visibility filtering happens at the *prefix-resolution* step,
so a joint run never even learns private locations.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 + Alembic, phase-1a `penny.tenancy`
(`RequestContext`, `SessionMode`, `session_for`), the existing functional R2
adapter (`store_object_in_r2` / `download_object_from_r2` / `R2Config`),
`secrets.token_urlsafe` for opaque prefix tokens, `hashlib.sha256` for
content addressing.

## Design refinement vs. spec

The spec says "a single compare-and-set on the **household** workspace head."
Working out joint-mode flush showed that a *single household-wide* head cannot
work with row-level security: a joint run's flush would have to copy forward
private manifest entries **it is not allowed to read**, so private files would
vanish from the head. The plan therefore uses **one manifest chain + head per
prefix** (shared, private-per-user). Each CAS is still atomic and lost-update
safe; a joint run only ever holds the shared prefix's head, so the spec's core
guarantees (atomicity, joint-can't-touch-private, no half-applied commit) are
preserved — strengthened, in fact. A run that edits both shared and private
files performs one CAS per touched prefix; each prefix stays internally
consistent, and a failed CAS retries independently. The spec has been annotated
to match.

**Conflict re-apply (v1):** on CAS failure, re-materialize the new head and
re-apply this run's changed files **per-file last-writer-wins** (no 3-way
merge). Memory/rules are append-ish markdown; the loser's overwrite of a
same-file concurrent edit is acceptable for a two-user household and is
recorded as a future refinement.

## Global Constraints

- **Verification gate (run before completing every task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Depends on phase 1a** (`penny.tenancy`, `Household`/`User`, RLS plumbing,
  `pg_db` fixture, `@pytest.mark.postgres` marker).
- **Prefix tokens are opaque** (`secrets.token_urlsafe(24)`), never derived from
  household/user ids. R2 keys are derived **only** from RLS-gated Postgres rows.
- **The agent never touches R2** — only the workspace shim does. No R2 calls
  from tool code.
- **Blobs are immutable** and content-addressed (`{prefix_token}/{sha256hex}`);
  uploads are idempotent and safe before the CAS; orphans from losing races are
  harmless (GC is out of scope for v1).
- **Migration numbering:** this plan uses revision `015_add_workspace_store`
  (after phase-1a's `006`–`013` and phase-2's possible `014`); renumber to the
  next free slot at execution time if needed.
- Tests that need R2 use the injectable `BlobStore` fake — no network in tests.
- New env: none beyond the existing `R2_*` vars (`.env.example` already has
  them); document the workspace layout in `.env.example` comments.

## File structure

- Create: `backend/penny/workspace_store/__init__.py`
- Create: `backend/penny/workspace_store/blobs.py` — `BlobStore` protocol,
  `R2BlobStore` (wraps the existing adapter), `InMemoryBlobStore` (tests).
- Create: `backend/penny/workspace_store/broker.py` — prefix
  creation/resolution (the capability broker).
- Create: `backend/penny/workspace_store/sync.py` — `materialize` / `flush` +
  `WorkspaceCheckout`.
- Modify: `backend/penny/adapters/db/models.py` — `WorkspacePrefix`,
  `WorkspaceManifest`, `WorkspaceHead`.
- Create: `backend/db/migrations/015_add_workspace_store.py` (tables + RLS,
  dialect-guarded).
- Modify: `backend/penny/agent_factory.py` — memory assembly reads a checkout
  dir; `backend/penny/api/main.py` + `backend/penny/cli.py` — materialize →
  run → flush around agent runs.
- Modify: `backend/penny/admin.py` — `import-workspace` command (one-time
  migration of `~/.transactoid`).
- Tests: `backend/tests/workspace_store/test_blobs.py`, `test_broker.py`,
  `test_sync.py`, `backend/tests/adapters/db/test_workspace_rls.py`
  (Postgres-marked).

---

### Task 1: `BlobStore` seam (protocol + R2 impl + in-memory fake)

**Files:**
- Create: `backend/penny/workspace_store/__init__.py`,
  `backend/penny/workspace_store/blobs.py`
- Test: `backend/tests/workspace_store/test_blobs.py`

**Interfaces:**
- Consumes: `store_object_in_r2`, `download_object_from_r2`, `R2Config`
  (`penny/adapters/storage/r2.py`).
- Produces:
  - `class BlobStore(Protocol)`: `put(key: str, body: bytes) -> None`,
    `get(key: str) -> bytes`, `exists(key: str) -> bool`.
  - `class R2BlobStore(BlobStore)` — thin wrapper over the adapter functions
    (`content_type="application/octet-stream"`); `exists` via a `get` guarded
    by the adapter's not-found error (documented acceptable for v1 — `put` is
    idempotent so `exists` is an optimization only).
  - `class InMemoryBlobStore(BlobStore)` — dict-backed, for every non-R2 test.
  - `content_key(prefix_token: str, body: bytes) -> str` returning
    `f"{prefix_token}/{hashlib.sha256(body).hexdigest()}"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workspace_store/test_blobs.py
from penny.workspace_store.blobs import InMemoryBlobStore, content_key


def test_content_key_is_prefix_plus_sha256():
    key = content_key("tokABC", b"hello")
    assert key.startswith("tokABC/")
    assert len(key.split("/", 1)[1]) == 64


def test_inmemory_roundtrip():
    store = InMemoryBlobStore()
    key = content_key("tok", b"data")
    assert not store.exists(key)
    store.put(key, b"data")
    assert store.exists(key)
    assert store.get(key) == b"data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_blobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.workspace_store'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/workspace_store/__init__.py
```

```python
# backend/penny/workspace_store/blobs.py
from __future__ import annotations

import hashlib
from typing import Protocol

from penny.adapters.storage.r2 import download_object_from_r2, store_object_in_r2


def content_key(prefix_token: str, body: bytes) -> str:
    return f"{prefix_token}/{hashlib.sha256(body).hexdigest()}"


class BlobStore(Protocol):
    def put(self, key: str, body: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class InMemoryBlobStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        self._objects[key] = body

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def exists(self, key: str) -> bool:
        return key in self._objects


class R2BlobStore:
    def put(self, key: str, body: bytes) -> None:
        store_object_in_r2(key=key, body=body,
                           content_type="application/octet-stream")

    def get(self, key: str) -> bytes:
        return download_object_from_r2(key=key)

    def exists(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/workspace_store/test_blobs.py -v` → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/workspace_store backend/tests/workspace_store/test_blobs.py
git commit -m "feat(workspace): BlobStore seam (R2 impl + in-memory fake, content-addressed keys)"
```

---

### Task 2: Workspace tables + migration 015 (+ RLS)

**Files:**
- Modify: `backend/penny/adapters/db/models.py`
- Create: `backend/db/migrations/015_add_workspace_store.py`
- Modify: `backend/alembic/env.py` (import the three models)
- Test: `backend/tests/workspace_store/test_models.py`

**Interfaces:**
- Produces:

```python
class WorkspacePrefix(Base):
    __tablename__ = "workspace_prefixes"
    prefix_token: Mapped[str] = mapped_column(String, primary_key=True)  # opaque
    household_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("households.household_id"), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.user_id"), nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False)  # 'private' | 'shared'
    kind: Mapped[str] = mapped_column(String, nullable=False)        # 'shared' | 'private'
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WorkspaceManifest(Base):
    __tablename__ = "workspace_manifests"
    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prefix_token: Mapped[str] = mapped_column(String, ForeignKey("workspace_prefixes.prefix_token"), nullable=False)
    parent_manifest_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    entries: Mapped[list[dict]] = mapped_column(JSON, nullable=False)  # [{"path","sha256","size"}]
    household_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)   # denormalized
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # denormalized
    visibility: Mapped[str] = mapped_column(String, nullable=False)          # denormalized
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WorkspaceHead(Base):
    __tablename__ = "workspace_heads"
    prefix_token: Mapped[str] = mapped_column(String, ForeignKey("workspace_prefixes.prefix_token"), primary_key=True)
    head_manifest_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    household_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False)
```

  Constraints in the migration: unique partial index `one shared prefix per
  household` (`household_id` where `kind='shared'`); unique partial index `one
  private prefix per owner` (`owner_user_id` where `kind='private'`);
  `CHECK (visibility IN ('private','shared'))`; on Postgres, the phase-1a
  user-centric `tenant_isolation` policy (USING **and WITH CHECK**) on all three
  tables + `FORCE ROW LEVEL SECURITY`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workspace_store/test_models.py
import uuid
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    Household, User, WorkspaceHead, WorkspaceManifest, WorkspacePrefix,
)


def test_workspace_tables_round_trip(tmp_path: Path):
    db = DB(f"sqlite:///{tmp_path / 't.db'}")
    db.create_schema()
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        p = WorkspacePrefix(prefix_token="tok1", household_id=hh.household_id,
                            owner_user_id=u.user_id, visibility="shared", kind="shared")
        s.add(p); s.flush()
        m = WorkspaceManifest(prefix_token="tok1", parent_manifest_id=None,
                              entries=[{"path": "memory/index.md", "sha256": "0" * 64, "size": 3}],
                              household_id=hh.household_id, owner_user_id=u.user_id,
                              visibility="shared")
        s.add(m); s.flush()
        s.add(WorkspaceHead(prefix_token="tok1", head_manifest_id=m.manifest_id,
                            household_id=hh.household_id, owner_user_id=u.user_id,
                            visibility="shared"))
        s.flush()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'WorkspacePrefix'`.

- [ ] **Step 3: Write minimal implementation**

Add the three models above to `models.py` (with `JSON` imported from
`sqlalchemy`), import them in `alembic/env.py`, and write migration
`015_add_workspace_store.py` (`down_revision` = current chain head at execution
time): `op.create_table` × 3 mirroring the models, the two partial unique
indexes, the visibility CHECKs, and — guarded by
`if op.get_bind().dialect.name == "postgresql":` — `ENABLE`/`FORCE ROW LEVEL
SECURITY` plus the `tenant_isolation` policy with both `USING` and `WITH CHECK`
using the phase-1a predicate. `downgrade()` drops policies then tables.

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/workspace_store/test_models.py -v` → PASS.
Run: `cd backend && DATABASE_URL="sqlite:///$(mktemp -u).db" <phase-1a env vars> uv run alembic upgrade head` → ends at `015`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/alembic/env.py \
  backend/db/migrations/015_add_workspace_store.py \
  backend/tests/workspace_store/test_models.py
git commit -m "feat(workspace): prefix/manifest/head tables with RLS (migration 015)"
```

---

### Task 3: Broker — ensure + resolve prefixes

**Files:**
- Create: `backend/penny/workspace_store/broker.py`
- Test: `backend/tests/workspace_store/test_broker.py`

**Interfaces:**
- Consumes: the Task-2 models; `RequestContext`, `SessionMode`.
- Produces:
  - `@dataclass(frozen=True) PrefixInfo(prefix_token: str, visibility: str,
    owner_user_id: uuid.UUID)`.
  - `ensure_prefixes(session, ctx) -> None` — lazily creates (idempotently) the
    household's shared prefix and, in individual mode, the user's private
    prefix. Tokens via `secrets.token_urlsafe(24)`.
  - `resolve_readable_prefixes(session, ctx) -> list[PrefixInfo]` — individual:
    `[private(ctx.user), shared(household)]`; joint: `[shared(household)]`
    **only** — private rows are never queried in joint mode (and RLS would hide
    other users' anyway).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workspace_store/test_broker.py
import uuid

from penny.adapters.db.models import Household, User, WorkspacePrefix
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode
from penny.workspace_store.broker import ensure_prefixes, resolve_readable_prefixes


def _seed(db):
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        a = User(household_id=hh.household_id, email="a@x.com")
        b = User(household_id=hh.household_id, email="b@x.com")
        s.add_all([a, b]); s.flush()
        return hh.household_id, a.user_id, b.user_id


def test_ensure_is_idempotent_and_tokens_opaque(isolated_db):
    db = get_db(); db.create_schema()
    hid, ua, _ = _seed(db)
    ctx = RequestContext(user_id=ua, household_id=hid)
    with db.session() as s:
        ensure_prefixes(s, ctx)
        ensure_prefixes(s, ctx)  # no duplicates
        rows = s.query(WorkspacePrefix).all()
        assert len(rows) == 2  # one shared + one private(a)
        for r in rows:
            assert str(hid) not in r.prefix_token and str(ua) not in r.prefix_token


def test_individual_resolves_private_plus_shared(isolated_db):
    db = get_db(); db.create_schema()
    hid, ua, _ = _seed(db)
    ctx = RequestContext(user_id=ua, household_id=hid)
    with db.session() as s:
        ensure_prefixes(s, ctx)
        infos = resolve_readable_prefixes(s, ctx)
    assert sorted(i.visibility for i in infos) == ["private", "shared"]


def test_joint_resolves_shared_only(isolated_db):
    db = get_db(); db.create_schema()
    hid, ua, ub = _seed(db)
    for u in (ua, ub):
        with db.session() as s:
            ensure_prefixes(s, RequestContext(user_id=u, household_id=hid))
    joint = RequestContext(user_id=ua, household_id=hid, session_mode=SessionMode.JOINT)
    with db.session() as s:
        infos = resolve_readable_prefixes(s, joint)
    assert [i.visibility for i in infos] == ["shared"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_broker.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/workspace_store/broker.py
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from penny.adapters.db.models import WorkspaceHead, WorkspacePrefix
from penny.tenancy.context import RequestContext, SessionMode


@dataclass(frozen=True, slots=True)
class PrefixInfo:
    prefix_token: str
    visibility: str
    owner_user_id: uuid.UUID


def _create(session: Session, ctx: RequestContext, *, kind: str, visibility: str) -> None:
    token = secrets.token_urlsafe(24)
    session.add(WorkspacePrefix(prefix_token=token, household_id=ctx.household_id,
                                owner_user_id=ctx.user_id, visibility=visibility,
                                kind=kind))
    session.add(WorkspaceHead(prefix_token=token, head_manifest_id=None,
                              household_id=ctx.household_id,
                              owner_user_id=ctx.user_id, visibility=visibility))
    session.flush()


def ensure_prefixes(session: Session, ctx: RequestContext) -> None:
    shared = session.query(WorkspacePrefix).filter(
        WorkspacePrefix.household_id == ctx.household_id,
        WorkspacePrefix.kind == "shared",
    ).one_or_none()
    if shared is None:
        _create(session, ctx, kind="shared", visibility="shared")
    if ctx.session_mode is SessionMode.INDIVIDUAL:
        private = session.query(WorkspacePrefix).filter(
            WorkspacePrefix.owner_user_id == ctx.user_id,
            WorkspacePrefix.kind == "private",
        ).one_or_none()
        if private is None:
            _create(session, ctx, kind="private", visibility="private")


def resolve_readable_prefixes(session: Session, ctx: RequestContext) -> list[PrefixInfo]:
    query = session.query(WorkspacePrefix).filter(
        WorkspacePrefix.household_id == ctx.household_id,
        WorkspacePrefix.kind == "shared",
    )
    rows = list(query.all())
    if ctx.session_mode is SessionMode.INDIVIDUAL:
        rows += list(
            session.query(WorkspacePrefix).filter(
                WorkspacePrefix.owner_user_id == ctx.user_id,
                WorkspacePrefix.kind == "private",
            ).all()
        )
    # private first so shared files win path collisions deterministically? No:
    # shared first, private second — private overlays shared on materialize.
    rows.sort(key=lambda r: 0 if r.kind == "shared" else 1)
    return [PrefixInfo(r.prefix_token, r.visibility, r.owner_user_id) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/workspace_store/test_broker.py -v` → PASS (3).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/workspace_store/broker.py backend/tests/workspace_store/test_broker.py
git commit -m "feat(workspace): capability broker (lazy opaque prefixes, mode-filtered resolution)"
```

---

### Task 4: Materialize — head manifests → temp checkout

**Files:**
- Create: `backend/penny/workspace_store/sync.py`
- Test: `backend/tests/workspace_store/test_sync.py`

**Interfaces:**
- Consumes: `PrefixInfo`, models, `BlobStore`.
- Produces:
  - `@dataclass WorkspaceCheckout(root: Path, baselines: dict[str, ManifestSnapshot],
    prefixes: list[PrefixInfo])` where
    `ManifestSnapshot = (manifest_id: uuid.UUID | None, entries: dict[path, sha256])`.
  - `materialize(session, ctx, *, blob_store: BlobStore, root: Path) ->
    WorkspaceCheckout` — for each readable prefix (broker order: shared first,
    private overlays), read `WorkspaceHead` → manifest → download each entry to
    `root/<path>`. Empty head → empty baseline. Records which prefix each path
    came from (`checkout.origin: dict[path, prefix_token]`) for visibility-routed
    write-back.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workspace_store/test_sync.py
import uuid
from pathlib import Path

from penny.adapters.db.models import Household, User, WorkspaceHead, WorkspaceManifest
from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore, content_key
from penny.workspace_store.broker import ensure_prefixes, resolve_readable_prefixes
from penny.workspace_store.sync import materialize


def _seed_with_content(db, blob_store):
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
        ensure_prefixes(s, ctx)
        infos = resolve_readable_prefixes(s, ctx)
        shared = next(i for i in infos if i.visibility == "shared")
        body = b"# merchant rules\n"
        key = content_key(shared.prefix_token, body)
        blob_store.put(key, body)
        m = WorkspaceManifest(
            prefix_token=shared.prefix_token, parent_manifest_id=None,
            entries=[{"path": "memory/merchant-rules.md",
                      "sha256": key.split("/", 1)[1], "size": len(body)}],
            household_id=ctx.household_id, owner_user_id=ctx.user_id,
            visibility="shared",
        )
        s.add(m); s.flush()
        s.query(WorkspaceHead).filter_by(prefix_token=shared.prefix_token).update(
            {"head_manifest_id": m.manifest_id}
        )
        return ctx


def test_materialize_writes_head_content(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    f = checkout.root / "memory" / "merchant-rules.md"
    assert f.read_bytes() == b"# merchant rules\n"
    assert checkout.origin["memory/merchant-rules.md"]  # prefix recorded


def test_materialize_empty_head_yields_empty_checkout(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
        ensure_prefixes(s, ctx)
        checkout = materialize(s, ctx, blob_store=InMemoryBlobStore(),
                               root=tmp_path / "run")
    assert list(checkout.root.rglob("*")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_sync.py -v`
Expected: FAIL — `ModuleNotFoundError` on `penny.workspace_store.sync`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/workspace_store/sync.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

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
    manifest = session.query(WorkspaceManifest).filter_by(
        manifest_id=head.head_manifest_id
    ).one()
    return ManifestSnapshot(
        manifest_id=manifest.manifest_id,
        entries={e["path"]: e["sha256"] for e in manifest.entries},
    )


def materialize(
    session: Session, ctx: RequestContext, *, blob_store: BlobStore, root: Path
) -> WorkspaceCheckout:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/workspace_store/test_sync.py -v` → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/workspace_store/sync.py backend/tests/workspace_store/test_sync.py
git commit -m "feat(workspace): materialize head manifests into a per-run checkout"
```

---

### Task 5: Flush — diff, upload, CAS, retry, visibility routing

**Files:**
- Modify: `backend/penny/workspace_store/sync.py`
- Test: `backend/tests/workspace_store/test_sync.py`

**Interfaces:**
- Produces: `flush(session, ctx, checkout, *, blob_store: BlobStore,
  max_retries: int = 3) -> dict[str, uuid.UUID]` (new head manifest per touched
  prefix token; empty dict when nothing changed). Behavior:
  1. Walk `checkout.root`; hash every file; compare against the union of
     baselines to find changed/new/deleted paths.
  2. **Route** each change: existing path → its `origin` prefix; **new** path →
     the private prefix in individual mode, the shared prefix in joint mode.
  3. Per touched prefix: upload changed blobs first (`content_key`; skip if
     `exists`), then build the new entry list (baseline entries ± changes) and
     attempt the CAS:
     `UPDATE workspace_heads SET head_manifest_id=:new WHERE prefix_token=:p
     AND head_manifest_id IS NOT DISTINCT FROM :parent` — rowcount 0 → conflict:
     reload the head, re-materialize that prefix's entries, re-apply this run's
     changes per-file (last-writer-wins), retry; raise `FlushConflictError`
     after `max_retries`.
  4. An aborted run simply never calls `flush` — nothing is committed.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/workspace_store/test_sync.py
from penny.workspace_store.sync import flush


def test_flush_commits_changed_and_new_files(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
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


def test_new_file_in_individual_mode_lands_in_private_prefix(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
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
    db = get_db(); db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    with db.session() as s:
        checkout = materialize(s, ctx, blob_store=blobs, root=tmp_path / "run")
    with db.session() as s:
        assert flush(s, ctx, checkout, blob_store=blobs) == {}


def test_concurrent_flush_retries_and_preserves_both_edits(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_sync.py -k flush -v`
Expected: FAIL — `ImportError: cannot import name 'flush'`.

- [ ] **Step 3: Write minimal implementation**

Add to `sync.py`:

```python
class FlushConflictError(Exception):
    """CAS kept failing after retries."""


def _route_new_path(checkout: WorkspaceCheckout, ctx: RequestContext) -> str:
    from penny.tenancy.context import SessionMode
    want = "private" if ctx.session_mode is SessionMode.INDIVIDUAL else "shared"
    for info in checkout.prefixes:
        if info.visibility == want:
            return info.prefix_token
    return checkout.prefixes[0].prefix_token  # joint: shared is the only prefix


def flush(session, ctx, checkout, *, blob_store, max_retries: int = 3):
    import hashlib

    from sqlalchemy import text as sqltext

    from penny.adapters.db.models import WorkspaceManifest

    # 1. Current working-tree state.
    current: dict[str, bytes] = {}
    for f in checkout.root.rglob("*"):
        if f.is_file():
            current[str(f.relative_to(checkout.root))] = f.read_bytes()

    # 2. Per-prefix change sets (path -> bytes | None for delete).
    changes: dict[str, dict[str, bytes | None]] = {}
    baseline_union = {p: (tok, sha) for tok, snap in checkout.baselines.items()
                      for p, sha in snap.entries.items()}
    for path, body in current.items():
        sha = hashlib.sha256(body).hexdigest()
        known = baseline_union.get(path)
        if known is None:
            changes.setdefault(_route_new_path(checkout, ctx), {})[path] = body
        elif known[1] != sha:
            changes.setdefault(checkout.origin[path], {})[path] = body
    for path, (tok, _sha) in baseline_union.items():
        if path not in current:
            changes.setdefault(tok, {})[path] = None  # deleted

    new_heads: dict[str, uuid.UUID] = {}
    for token, delta in changes.items():
        parent = checkout.baselines.get(token, ManifestSnapshot(None, {}))
        for attempt in range(max_retries + 1):
            entries = dict(parent.entries)
            for path, body in delta.items():
                if body is None:
                    entries.pop(path, None)
                else:
                    sha = hashlib.sha256(body).hexdigest()
                    key = f"{token}/{sha}"
                    if not blob_store.exists(key):
                        blob_store.put(key, body)  # immutable, pre-CAS, safe
                    entries[path] = sha
            info = next(i for i in checkout.prefixes if i.prefix_token == token)
            manifest = WorkspaceManifest(
                prefix_token=token, parent_manifest_id=parent.manifest_id,
                entries=[{"path": p, "sha256": s, "size": 0} for p, s in entries.items()],
                household_id=ctx.household_id, owner_user_id=info.owner_user_id,
                visibility=info.visibility,
            )
            session.add(manifest)
            session.flush()
            result = session.execute(
                sqltext(
                    "UPDATE workspace_heads SET head_manifest_id = :new "
                    "WHERE prefix_token = :tok AND head_manifest_id IS NOT DISTINCT FROM :parent"
                ),
                {"new": str(manifest.manifest_id), "tok": token,
                 "parent": str(parent.manifest_id) if parent.manifest_id else None},
            )
            if result.rowcount == 1:
                new_heads[token] = manifest.manifest_id
                break
            # Conflict: adopt the moved head as the new parent and re-apply.
            session.expire_all()
            parent = _head_snapshot(session, token)
        else:
            raise FlushConflictError(f"prefix {token} kept moving")
    return new_heads
```

> SQLite note: `IS NOT DISTINCT FROM` needs SQLite ≥3.39 (`IS` also works there);
> use `sqlalchemy` portability if the raw text fails on either dialect —
> acceptance is the tests passing on both SQLite and Postgres.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/workspace_store/test_sync.py -v` → PASS (6 total).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/workspace_store/sync.py backend/tests/workspace_store/test_sync.py
git commit -m "feat(workspace): flush with content-addressed upload + per-prefix CAS and retry"
```

---

### Task 6: Wire into agent runs (chat + cron) and memory assembly

**Files:**
- Modify: `backend/penny/agent_factory.py` (`_assemble_agent_memory` lines
  43-60; `build_agent` lines 144-174 — accept `workspace_dir: Path`)
- Modify: `backend/penny/api/main.py` (chat handler) and `backend/penny/cli.py`
  (`_drive_agent`) — materialize → run → flush
- Test: `backend/tests/workspace_store/test_agent_wiring.py`

**Interfaces:**
- Produces: `run_with_workspace(ctx, run_fn) -> Any` helper in
  `workspace_store/sync.py`:

```python
async def run_with_workspace(ctx, run_fn, *, blob_store=None):
    """materialize -> await run_fn(checkout_root) -> flush. Aborted run = no flush."""
```

  It creates a temp dir under the scratch area (`tempfile.mkdtemp(prefix="penny-ws-")`),
  materializes, awaits `run_fn(Path)`, flushes on success, and always deletes
  the temp dir in `finally`. `blob_store=None` → `R2BlobStore()`.
  `_assemble_agent_memory(workspace_dir)` reads `memory/*.md` from the checkout
  instead of `resolve_memory_dir()`; `build_agent(..., ctx, workspace_dir)`
  threads it through; the chat handler and `_drive_agent` wrap their agent run
  in `run_with_workspace`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/workspace_store/test_agent_wiring.py
from pathlib import Path

from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore
from penny.workspace_store.sync import run_with_workspace
from tests.workspace_store.test_sync import _seed_with_content  # reuse seed


async def test_run_with_workspace_materializes_runs_and_flushes(isolated_db, tmp_path):
    db = get_db(); db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    seen: dict = {}

    async def fake_run(root: Path):
        seen["had_rules"] = (root / "memory" / "merchant-rules.md").exists()
        (root / "memory" / "learned.md").write_bytes(b"lesson\n")
        return "ok"

    result = await run_with_workspace(ctx, fake_run, blob_store=blobs)
    assert result == "ok" and seen["had_rules"]
    # flushed: a fresh materialize sees the new file
    from penny.workspace_store.sync import materialize
    with get_db().session() as s:
        again = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert (again.root / "memory" / "learned.md").exists()


async def test_aborted_run_commits_nothing(isolated_db, tmp_path):
    db = get_db(); db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)

    async def crashing_run(root: Path):
        (root / "memory" / "half-done.md").write_bytes(b"partial\n")
        raise RuntimeError("boom")

    import pytest
    with pytest.raises(RuntimeError):
        await run_with_workspace(ctx, crashing_run, blob_store=blobs)
    from penny.workspace_store.sync import materialize
    with get_db().session() as s:
        again = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert not (again.root / "memory" / "half-done.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/workspace_store/test_agent_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_with_workspace'`.

- [ ] **Step 3: Write minimal implementation**

Add `run_with_workspace` to `sync.py`:

```python
import shutil
import tempfile


async def run_with_workspace(ctx, run_fn, *, blob_store=None):
    from penny.db import get_db
    from penny.workspace_store.blobs import R2BlobStore
    from penny.workspace_store.broker import ensure_prefixes

    store = blob_store if blob_store is not None else R2BlobStore()
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
```

Then: change `_assemble_agent_memory` to take `workspace_dir: Path` and read
`workspace_dir / "memory"`; add `workspace_dir` (and `ctx`, from phase-2 Task 6
if present) to `build_agent` and `_render_system_prompt`; in the chat handler
and `cli._drive_agent`, wrap the existing `agent.run(...)` call as
`await run_with_workspace(turn_ctx, lambda root: _run_agent(root, ...))` where
`_run_agent` builds the agent with `workspace_dir=root` and runs it. Reports
tools that wrote to `resolve_reports_dir()` write to
`workspace_dir / "reports"` (thread the checkout root through the toolset
factory the same way).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/workspace_store/test_agent_wiring.py -v`
→ PASS (2). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/workspace_store/sync.py backend/penny/agent_factory.py \
  backend/penny/api/main.py backend/penny/cli.py \
  backend/tests/workspace_store/test_agent_wiring.py
git commit -m "feat(workspace): materialize/flush around every agent run; memory reads the checkout"
```

---

### Task 7: `penny admin import-workspace` (one-time migration)

**Files:**
- Modify: `backend/penny/admin.py`
- Test: `backend/tests/test_admin_import_workspace.py`

**Interfaces:**
- Consumes: broker + sync + `BlobStore`.
- Produces: `import_workspace(ctx, source_dir: Path, *, blob_store) ->
  dict[str, uuid.UUID]` — imports `source_dir/memory/**` and
  `source_dir/reports/**` into the **user's private prefix** (strict default,
  matching the phase-1a "everything private until shared" posture; promote
  files to shared later by editing in a shared context). Implemented as:
  materialize an empty/current checkout, copy the files in, `flush`. Command:
  `penny admin import-workspace --household <uuid> --user <uuid>
  --source ~/.transactoid`. Idempotent (unchanged files produce no new
  manifest).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_import_workspace.py
from pathlib import Path

from penny.admin import import_workspace
from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore
from penny.workspace_store.sync import materialize
from penny.adapters.db.models import Household, User


def test_import_lands_in_private_prefix_and_is_idempotent(isolated_db, tmp_path: Path):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
    src = tmp_path / "old-workspace"
    (src / "memory").mkdir(parents=True)
    (src / "memory" / "index.md").write_text("# memory\n")
    blobs = InMemoryBlobStore()

    first = import_workspace(ctx, src, blob_store=blobs)
    second = import_workspace(ctx, src, blob_store=blobs)  # no changes
    assert first and second == {}

    with db.session() as s:
        out = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert (out.root / "memory" / "index.md").read_text() == "# memory\n"
    private = next(i for i in out.prefixes if i.visibility == "private")
    assert out.origin["memory/index.md"] == private.prefix_token
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_admin_import_workspace.py -v`
Expected: FAIL — `ImportError: cannot import name 'import_workspace'`.

- [ ] **Step 3: Write minimal implementation**

Add to `admin.py`: `import_workspace(ctx, source_dir, *, blob_store=None)` —
temp checkout via `materialize` (after `ensure_prefixes`), copy
`source_dir/{memory,reports}` into the checkout root **as new files** (new
files route private in individual mode per Task 5), call `flush`, return its
result; plus the Typer command wrapping it (`--household`, `--user`,
`--source`, default `~/.transactoid`). Reuse `run_with_workspace`'s
session/teardown pattern synchronously (plain function, same materialize/flush
calls).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_admin_import_workspace.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/admin.py backend/tests/test_admin_import_workspace.py
git commit -m "feat(admin): import-workspace migrates ~/.transactoid into the private prefix"
```

---

### Task 8: Postgres RLS suite for the workspace tables

**Files:**
- Create: `backend/tests/adapters/db/test_workspace_rls.py` (Postgres-marked)

**Interfaces:** consumes `pg_db` (phase 1a), broker, sync, `InMemoryBlobStore`.

- [ ] **Step 1: Write the battery** — concrete tests (seed two households A/B,
  two users each, content in every prefix, mirroring Task 3/4 seeds):

```python
# backend/tests/adapters/db/test_workspace_rls.py — names and assertions:
# test_cross_household_prefixes_invisible      (A's ctx: SELECT * FROM workspace_prefixes returns only A rows)
# test_spouse_private_prefix_invisible         (B's private prefix/manifest rows hidden from A even via raw SQL)
# test_joint_ctx_cannot_select_private_rows    (nil-sentinel ctx: only visibility='shared' rows return)
# test_joint_materialize_never_touches_private (materialize in joint mode: origin map has no private prefix, temp dir has no private files)
# test_with_check_blocks_foreign_household_insert (INSERT a prefix row with B's household_id from A's ctx -> rejected)
```

- [ ] **Step 2–3:** Run
  `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_workspace_rls.py -v`,
  implement/fix until all pass; skipped without the env var; full gate green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/adapters/db/test_workspace_rls.py
git commit -m "test(workspace): RLS isolation battery (cross-household, private, joint, WITH CHECK)"
```

---

## Browser E2E Validation (Playwright)

The unit/RLS suites prove the workspace round-trips at the store seam. This task
proves it through the *real UI*: memory saved by the agent in one chat is
recalled by the agent in a later chat, which only works if the R2 blob upload +
Postgres manifest CAS actually committed and re-materialized across runs. It
reuses the phase-1a Playwright harness (dev-mode backend + vite, the pinned dev
principal) — no new harness scaffolding here.

### Task 9: Workspace memory round-trips through the UI (E2E)

**Files:**
- Create: `frontend/e2e/workspace-memory.spec.ts`

**Interfaces:**
- Consumes: the `test` fixture + `webServer` from phase-1a Task 15 (backend in
  `PENNY_AUTH_MODE=dev` with `PENNY_DEV_USER_ID`/`PENNY_DEV_HOUSEHOLD_ID` pinned).
  Requires the workspace hybrid wired into agent runs (Task 6) so chat runs
  materialize → run → flush.

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/workspace-memory.spec.ts
import { test, expect } from "./fixtures/app";

const FACT = `my favorite coffee is a cortado (${Date.now()})`;

test("agent saves a memory in one chat and recalls it in a later chat", async ({ page }) => {
  // Run 1: ask the agent to remember a fact -> flush writes it to R2 + a manifest.
  await page.goto("/");
  let composer = page.getByRole("textbox");
  await composer.fill(`Please remember this for later: ${FACT}. Save it to memory.`);
  await composer.press("Enter");
  const saved = page.locator('[data-role="assistant"]').last();
  await expect(saved).toBeVisible({ timeout: 30_000 });
  await expect(saved).not.toBeEmpty();

  // Run 2: a fresh chat load re-materializes the workspace head from R2+manifest.
  await page.reload();
  composer = page.getByRole("textbox");
  await composer.fill("What is my favorite coffee? Check your memory.");
  await composer.press("Enter");
  const recalled = page.locator('[data-role="assistant"]').last();
  await expect(recalled).toContainText(/cortado/i, { timeout: 30_000 });
});
```

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/workspace-memory.spec.ts`
Expected: FAIL — before the workspace wiring lands (or if the flush/materialize
path is incomplete) the second chat has no memory of the fact, so the
`toContainText(/cortado/i)` assertion times out.

- [ ] **Step 3: Make it pass**

Ensure Task 6's `run_with_workspace` wraps the chat handler so run 1's flush
persists `memory/*.md` and run 2's materialize re-hydrates it into the checkout
that feeds `{{AGENT_MEMORY}}`. Reuse the message selectors established in
phase-1a Task 16 (`data-role="assistant"` / the message-list `data-testid`). If
the CI model key is absent, gate the spec behind the same
`test.skip(!process.env.PENNY_E2E_MODEL)` guard used by the chat smoke spec, and
document that this spec needs a model that will actually call the memory tool.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/workspace-memory.spec.ts`
Expected: PASS (1 passed) — the fact saved in run 1 is recalled in run 2,
proving the R2 + manifest workspace round-trips through the real UI.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/workspace-memory.spec.ts
git commit -m "test(e2e): workspace memory round-trips through the UI across chat runs"
```

---

## Self-Review

**Spec coverage:** opaque tokens + visibility-partitioned layout → Tasks 2–3;
RLS-gated lookup before any R2 fetch, joint-never-resolves-private → Tasks 3–4,
8; per-run temp dir torn down after → Task 6; upload-blobs-then-single-CAS,
retry on conflict, aborted-run-commits-nothing → Tasks 5–6; visibility-routed
write-back + new-file defaults (private/individual, shared/joint) → Task 5;
manifests over immutable blobs + append-only history → Tasks 2, 5; memory
loader per session mode → Task 6; workspace test suite (joint/concurrent/abort)
→ Tasks 5, 6, 8; existing-workspace migration → Task 7. **Deviation:**
per-prefix heads instead of one household head — documented in "Design
refinement vs. spec" with rationale; spec annotated. R2 `LIST`-restricted
credentials and GC are deferred to phase 6 / later hardening (noted in
constraints).

**Placeholder scan:** Task 8 specifies its battery by exact test name +
assertion (pattern established by phase-1a Task 14); `size: 0` in flush's
manifest entries is a deliberate simplification (size is informational, not
load-bearing — hashes drive everything); all other code is complete. No
TBD/TODO.

**Type consistency:** `PrefixInfo`, `ManifestSnapshot(manifest_id, entries)`,
`WorkspaceCheckout(root, prefixes, baselines, origin)`, `materialize(session,
ctx, *, blob_store, root)`, `flush(session, ctx, checkout, *, blob_store,
max_retries)`, `run_with_workspace(ctx, run_fn, *, blob_store)`,
`content_key(prefix_token, body)`, `import_workspace(ctx, source_dir, *,
blob_store)` used consistently; phase-1a names (`RequestContext`,
`SessionMode`, `session_for`) match.

## Execution Handoff

Execute **after phase 1a** (models, tenancy, `pg_db`) and ideally alongside/after
phase 2 Task 6 (which introduces the turn context the chat wiring uses — if
phase 2 isn't built yet, Task 6 wires `ctx` from the dev-stub principal
instead). Postgres task (8) needs `POSTGRES_TEST_URL` on the Neon `penny-test`
branch. Subagent-driven execution recommended.
