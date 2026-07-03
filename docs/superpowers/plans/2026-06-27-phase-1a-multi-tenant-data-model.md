# Phase 1a — Multi-Tenant Data Model (Tenancy + RLS + Encryption) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [foundation design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Next:** [Phase 1b — Workspace hybrid](2026-06-27-phase-1b-workspace-hybrid.md)

**Goal:** Make the Penny backend multi-tenant — every financial row belongs to a
household and an owner, isolation is enforced by Postgres RLS plus app-level
filtering, and Plaid tokens are encrypted at rest — driven by a stubbed
`RequestContext` so it is testable before real auth (phase 2).

**Architecture:** A `households` / `users` identity model and a revived
`plaid_accounts` table carry ownership. Denormalized `household_id` /
`owner_user_id` / `visibility` columns on every financial table let RLS policies
stay join-free. A request-scoped `RequestContext` (carried via a `ContextVar`) is
read by the DB façade's `session()` context manager, which emits `SET LOCAL
app.current_household` / `app.current_user` so Postgres RLS filters every query —
including the agent's `run_sql`. App-level `WHERE` filtering is the
belt-and-suspenders second layer (and keeps SQLite dev correct). Workspace
storage moves in phase 1b.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`),
Alembic (custom version dir `backend/db/migrations/`), FastAPI, pytest
(`asyncio_mode=auto`, `--strict-markers`), `cryptography` (Fernet) for token
encryption, Postgres (Neon) in prod/test + SQLite for local dev.

## Global Constraints

- **Verification gate (run before completing every task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Env prefix:** new env vars use the `PENNY_*` prefix; keep `.env.example`
  current. New vars introduced here: `PENNY_DEV_USER_ID`,
  `PENNY_DEV_HOUSEHOLD_ID`, `PENNY_DEV_SESSION_MODE`, `PENNY_PLAID_TOKEN_KEY`.
- **Migrations:** append to the existing chain; current head is
  `005_seed_account_sign_conventions`. String revision IDs, `Revises:` chained.
  Every DDL migration must run on **both** Postgres and SQLite *except*
  RLS-specific DDL, which must be guarded with
  `if op.get_bind().dialect.name == "postgresql":` so SQLite dev skips it.
- **IDs:** new identity PKs and tenant FKs are `Uuid` (SQLAlchemy `Uuid` type →
  native `uuid` on Postgres, `CHAR(32)` on SQLite). The joint-session sentinel
  is the nil UUID `00000000-0000-0000-0000-000000000000`.
- **Visibility values:** the string literals `'private'` and `'shared'` only.
- **No raw secrets in logs.** Encrypted `access_token` is decrypted only at the
  Plaid call site.
- **RLS tests** are marked `@pytest.mark.postgres` and run only when
  `POSTGRES_TEST_URL` is set (Neon `penny-test` branch or local Postgres);
  otherwise skipped. The marker is registered in `pyproject.toml`.

## File structure

**New files:**
- `backend/penny/tenancy/__init__.py` — package.
- `backend/penny/tenancy/context.py` — `SessionMode`, `RequestContext`, the
  `ContextVar`, and accessors.
- `backend/penny/tenancy/principal.py` — dev-stub principal resolver
  (headers + env), returns a `RequestContext`.
- `backend/penny/security/__init__.py` — package.
- `backend/penny/security/token_cipher.py` — Fernet encrypt/decrypt for tokens.
- `backend/db/migrations/006_add_households_and_users.py`
- `backend/db/migrations/007_revive_plaid_accounts.py`
- `backend/db/migrations/008_add_tenant_columns_nullable.py`
- `backend/db/migrations/009_backfill_tenant_columns.py`
- `backend/db/migrations/010_tenant_columns_not_null_and_fks.py`
- `backend/db/migrations/011_enable_rls_policies.py`
- `backend/db/migrations/012_add_household_id_to_categories.py`
- `backend/db/migrations/013_encrypt_plaid_access_tokens.py`
- Tests: `backend/tests/tenancy/test_context.py`,
  `backend/tests/tenancy/test_principal.py`,
  `backend/tests/security/test_token_cipher.py`,
  `backend/tests/adapters/db/test_tenant_scoping.py`,
  `backend/tests/adapters/db/test_rls_isolation.py` (Postgres-marked),
  `backend/tests/conftest_postgres.py` (the `pg_db` fixture).

**Modified files:**
- `backend/penny/adapters/db/models.py` — new models + denormalized columns.
- `backend/penny/adapters/db/facade.py` — `session()` emits `SET LOCAL`;
  write-time denorm population; `WHERE` filtering on query methods.
- `backend/penny/api/main.py` — build `RequestContext`, set the `ContextVar`.
- `backend/penny/agent_factory.py` — accept `RequestContext`, pass to toolset.
- `backend/penny/bootstrap.py` — seed taxonomy per household.
- `backend/alembic/env.py` — import the new models.
- `backend/pyproject.toml` — register the `postgres` marker; add `cryptography`.
- `backend/.env.example` — document new env vars.

---

### Task 1: `RequestContext` + ContextVar

**Files:**
- Create: `backend/penny/tenancy/__init__.py`, `backend/penny/tenancy/context.py`
- Test: `backend/tests/tenancy/test_context.py`

**Interfaces:**
- Produces:
  - `class SessionMode(enum.Enum)` with members `INDIVIDUAL = "individual"`,
    `JOINT = "joint"`.
  - `@dataclass(frozen=True, slots=True) class RequestContext` with fields
    `user_id: uuid.UUID`, `household_id: uuid.UUID`,
    `session_mode: SessionMode = SessionMode.INDIVIDUAL`.
  - `NIL_USER_UUID: uuid.UUID` (the joint sentinel).
  - `effective_user_id(ctx: RequestContext) -> uuid.UUID` — returns
    `NIL_USER_UUID` when `ctx.session_mode is SessionMode.JOINT`, else
    `ctx.user_id`.
  - `set_request_context(ctx: RequestContext | None) -> contextvars.Token`,
    `get_request_context() -> RequestContext | None`,
    `require_request_context() -> RequestContext` (raises `LookupError` if unset),
    `reset_request_context(token) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/tenancy/test_context.py
import uuid

import pytest

from penny.tenancy.context import (
    NIL_USER_UUID,
    RequestContext,
    SessionMode,
    effective_user_id,
    get_request_context,
    require_request_context,
    reset_request_context,
    set_request_context,
)

U = uuid.UUID("11111111-1111-1111-1111-111111111111")
H = uuid.UUID("22222222-2222-2222-2222-222222222222")


def test_effective_user_is_real_in_individual_mode():
    ctx = RequestContext(user_id=U, household_id=H, session_mode=SessionMode.INDIVIDUAL)
    assert effective_user_id(ctx) == U


def test_effective_user_is_nil_in_joint_mode():
    ctx = RequestContext(user_id=U, household_id=H, session_mode=SessionMode.JOINT)
    assert effective_user_id(ctx) == NIL_USER_UUID


def test_contextvar_roundtrip_and_reset():
    assert get_request_context() is None
    ctx = RequestContext(user_id=U, household_id=H)
    token = set_request_context(ctx)
    assert require_request_context() is ctx
    reset_request_context(token)
    assert get_request_context() is None


def test_require_raises_when_unset():
    with pytest.raises(LookupError):
        require_request_context()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/tenancy/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.tenancy'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/tenancy/__init__.py
```

```python
# backend/penny/tenancy/context.py
from __future__ import annotations

import contextvars
import enum
import uuid
from dataclasses import dataclass

NIL_USER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class SessionMode(enum.Enum):
    INDIVIDUAL = "individual"
    JOINT = "joint"


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: uuid.UUID
    household_id: uuid.UUID
    session_mode: SessionMode = SessionMode.INDIVIDUAL


def effective_user_id(ctx: RequestContext) -> uuid.UUID:
    if ctx.session_mode is SessionMode.JOINT:
        return NIL_USER_UUID
    return ctx.user_id


_current: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "penny_request_context", default=None
)


def set_request_context(ctx: RequestContext | None) -> contextvars.Token:
    return _current.set(ctx)


def reset_request_context(token: contextvars.Token) -> None:
    _current.reset(token)


def get_request_context() -> RequestContext | None:
    return _current.get()


def require_request_context() -> RequestContext:
    ctx = _current.get()
    if ctx is None:
        raise LookupError("No RequestContext set for this execution context")
    return ctx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/tenancy/test_context.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/tenancy backend/tests/tenancy/test_context.py
git commit -m "feat(tenancy): RequestContext + ContextVar with joint-session sentinel"
```

---

### Task 2: Dev-stub principal resolver

**Files:**
- Create: `backend/penny/tenancy/principal.py`
- Test: `backend/tests/tenancy/test_principal.py`

**Interfaces:**
- Consumes: `RequestContext`, `SessionMode` from `penny.tenancy.context`.
- Produces:
  - `resolve_dev_principal(headers: Mapping[str, str]) -> RequestContext` —
    reads `X-Penny-User-Id`, `X-Penny-Household-Id`, `X-Penny-Session-Mode`
    (case-insensitive); falls back to env `PENNY_DEV_USER_ID`,
    `PENNY_DEV_HOUSEHOLD_ID`, `PENNY_DEV_SESSION_MODE` (default
    `"individual"`). Raises `ValueError` if neither header nor env supplies the
    user/household ids, or if ids are not valid UUIDs.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/tenancy/test_principal.py
import uuid

import pytest

from penny.tenancy.context import SessionMode
from penny.tenancy.principal import resolve_dev_principal

U = "11111111-1111-1111-1111-111111111111"
H = "22222222-2222-2222-2222-222222222222"


def test_resolves_from_headers():
    ctx = resolve_dev_principal(
        {"X-Penny-User-Id": U, "X-Penny-Household-Id": H, "X-Penny-Session-Mode": "joint"}
    )
    assert ctx.user_id == uuid.UUID(U)
    assert ctx.household_id == uuid.UUID(H)
    assert ctx.session_mode is SessionMode.JOINT


def test_header_case_insensitive_and_defaults_to_individual():
    ctx = resolve_dev_principal({"x-penny-user-id": U, "x-penny-household-id": H})
    assert ctx.session_mode is SessionMode.INDIVIDUAL


def test_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("PENNY_DEV_USER_ID", U)
    monkeypatch.setenv("PENNY_DEV_HOUSEHOLD_ID", H)
    ctx = resolve_dev_principal({})
    assert ctx.user_id == uuid.UUID(U)


def test_raises_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PENNY_DEV_USER_ID", raising=False)
    monkeypatch.delenv("PENNY_DEV_HOUSEHOLD_ID", raising=False)
    with pytest.raises(ValueError):
        resolve_dev_principal({})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/tenancy/test_principal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.tenancy.principal'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/tenancy/principal.py
from __future__ import annotations

import os
import uuid
from collections.abc import Mapping

from penny.tenancy.context import RequestContext, SessionMode


def _lower_keys(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _pick(headers: dict[str, str], header_name: str, env_name: str) -> str | None:
    value = headers.get(header_name)
    if value:
        return value
    env_value = os.environ.get(env_name, "").strip()
    return env_value or None


def resolve_dev_principal(headers: Mapping[str, str]) -> RequestContext:
    """Dev-only principal: header overrides env. Replaced by real auth in phase 2."""
    h = _lower_keys(headers)
    user_raw = _pick(h, "x-penny-user-id", "PENNY_DEV_USER_ID")
    household_raw = _pick(h, "x-penny-household-id", "PENNY_DEV_HOUSEHOLD_ID")
    if not user_raw or not household_raw:
        raise ValueError(
            "Dev principal unconfigured: set X-Penny-User-Id/X-Penny-Household-Id "
            "headers or PENNY_DEV_USER_ID/PENNY_DEV_HOUSEHOLD_ID env vars"
        )
    mode_raw = _pick(h, "x-penny-session-mode", "PENNY_DEV_SESSION_MODE") or "individual"
    return RequestContext(
        user_id=uuid.UUID(user_raw),
        household_id=uuid.UUID(household_raw),
        session_mode=SessionMode(mode_raw),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/tenancy/test_principal.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/tenancy/principal.py backend/tests/tenancy/test_principal.py
git commit -m "feat(tenancy): dev-stub principal resolver (headers + env)"
```

---

### Task 3: Identity models + migration 006

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (add `Household`, `User`)
- Create: `backend/db/migrations/006_add_households_and_users.py`
- Modify: `backend/alembic/env.py` (import `Household`, `User`)
- Test: `backend/tests/adapters/db/test_identity_models.py`

**Interfaces:**
- Produces:
  - `Household(Base)` → table `households`: `household_id: Mapped[uuid.UUID]`
    (PK, default `uuid4`), `name: Mapped[str]`, `created_at`.
  - `User(Base)` → table `users`: `user_id: Mapped[uuid.UUID]` (PK, default
    `uuid4`), `household_id: Mapped[uuid.UUID]` (FK→households), `email:
    Mapped[str]` (unique), `external_auth_id: Mapped[str | None]` (unique,
    nullable until phase 2), `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_identity_models.py
import uuid
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, User


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_household_and_user_round_trip(tmp_path):
    db = _create_db(tmp_path)
    with db.session() as session:
        hh = Household(name="Bossy")
        session.add(hh)
        session.flush()
        user = User(household_id=hh.household_id, email="adam@example.com")
        session.add(user)
        session.flush()
        assert isinstance(hh.household_id, uuid.UUID)
        assert user.household_id == hh.household_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_identity_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Household'`.

- [ ] **Step 3: Write minimal implementation**

Add to `backend/penny/adapters/db/models.py` (near the other models; ensure
`import uuid` and `from sqlalchemy import Uuid` are present):

```python
class Household(Base):
    __tablename__ = "households"

    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("households.household_id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    external_auth_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
```

Add to `backend/alembic/env.py` model imports: `Household,` and `User,`.

Create `backend/db/migrations/006_add_households_and_users.py`:

```python
"""Add households and users

Revision ID: 006_add_households_and_users
Revises: 005_seed_account_sign_conventions
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "006_add_households_and_users"
down_revision = "005_seed_account_sign_conventions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("household_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("external_auth_id", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.household_id"]),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("external_auth_id", name="uq_users_external_auth_id"),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("households")
```

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/adapters/db/test_identity_models.py -v`
Expected: PASS.
Run (migration applies cleanly on a throwaway SQLite db):
`cd backend && DATABASE_URL="sqlite:///$(mktemp -u).db" uv run alembic upgrade head`
Expected: ends at `006_add_households_and_users`, no error.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/alembic/env.py \
  backend/db/migrations/006_add_households_and_users.py \
  backend/tests/adapters/db/test_identity_models.py
git commit -m "feat(db): add households and users tables (migration 006)"
```

---

### Task 4: Revive `plaid_accounts` + migration 007

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (add `PlaidAccount`)
- Create: `backend/db/migrations/007_revive_plaid_accounts.py`
- Modify: `backend/alembic/env.py` (import `PlaidAccount`)
- Test: `backend/tests/adapters/db/test_plaid_accounts.py`

**Interfaces:**
- Consumes: `Household`, `User`, `PlaidItem`.
- Produces: `PlaidAccount(Base)` → table `plaid_accounts`:
  `account_id: Mapped[str]` (PK — matches Plaid's account id string and the
  existing `account_sign_conventions.account_id`), `item_id: Mapped[str]`
  (FK→plaid_items), `owner_user_id: Mapped[uuid.UUID]` (FK→users),
  `household_id: Mapped[uuid.UUID]` (FK→households), `visibility: Mapped[str]`
  (default `'private'`), `name: Mapped[str | None]`, `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_plaid_accounts.py
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidAccount, PlaidItem, User


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_plaid_account_links_item_owner_household(tmp_path):
    db = _create_db(tmp_path)
    with db.session() as session:
        hh = Household(name="Bossy")
        session.add(hh)
        session.flush()
        user = User(household_id=hh.household_id, email="a@example.com")
        item = PlaidItem(item_id="item-1", access_token="tok")
        session.add_all([user, item])
        session.flush()
        acct = PlaidAccount(
            account_id="acct-1",
            item_id="item-1",
            owner_user_id=user.user_id,
            household_id=hh.household_id,
            visibility="shared",
        )
        session.add(acct)
        session.flush()
        assert acct.visibility == "shared"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_plaid_accounts.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlaidAccount'`.

- [ ] **Step 3: Write minimal implementation**

Add to `models.py`:

```python
class PlaidAccount(Base):
    __tablename__ = "plaid_accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String, ForeignKey("plaid_items.item_id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id"), nullable=False
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("households.household_id"), nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'private'")
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
```

Add `PlaidAccount,` to `alembic/env.py` imports. Create
`backend/db/migrations/007_revive_plaid_accounts.py` (revision
`007_revive_plaid_accounts`, `down_revision = "006_add_households_and_users"`)
with the equivalent `op.create_table("plaid_accounts", …)`, FK constraints to
`plaid_items`, `users`, `households`, and `server_default=sa.text("'private'")`
on `visibility`. `downgrade()` drops the table.

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/adapters/db/test_plaid_accounts.py -v` → PASS.
Run: `cd backend && DATABASE_URL="sqlite:///$(mktemp -u).db" uv run alembic upgrade head` → ends at `007`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/alembic/env.py \
  backend/db/migrations/007_revive_plaid_accounts.py \
  backend/tests/adapters/db/test_plaid_accounts.py
git commit -m "feat(db): revive plaid_accounts with owner + visibility (migration 007)"
```

---

### Task 5: Expand — nullable tenant columns + migration 008

Adds `household_id` (Uuid, nullable), `owner_user_id` (Uuid, nullable),
`visibility` (String, nullable) to the **owner/visibility** tables, and only
`household_id` to the **household-term-only** tables. Columns are nullable here;
the contract migration (Task 7's revision 010) tightens them.

**Owner/visibility tables:** `plaid_items` (owner+household; no visibility — an
item's visibility is per-account), `plaid_transactions`, `derived_transactions`,
`transaction_items`, `transaction_tags`, `email_receipts`,
`pending_receipt_matches`, `account_sign_conventions`, `amazon_login_profiles`,
`amazon_orders`, `amazon_items`.
**Household-only tables:** `categories` (handled in Task 10 / migration 012),
`tags`, `transaction_category_events`.

> Note: `plaid_items` gets `household_id` + `owner_user_id` but **no**
> `visibility` column (visibility lives on `plaid_accounts`). All transaction
> rows get all three so the RLS policy is join-free.

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (add the columns to each model
  class listed above — `Mapped[uuid.UUID | None]` / `Mapped[str | None]` so the
  ORM matches the nullable DB state during this phase)
- Create: `backend/db/migrations/008_add_tenant_columns_nullable.py`
- Test: `backend/tests/adapters/db/test_tenant_columns_present.py`

**Interfaces:**
- Produces: every listed table has `household_id`; owner/visibility tables also
  have `owner_user_id` and (except `plaid_items`) `visibility`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_tenant_columns_present.py
from pathlib import Path

import sqlalchemy as sa

from penny.adapters.db.facade import DB

OWNER_VIS_TABLES = [
    "plaid_transactions", "derived_transactions", "transaction_items",
    "transaction_tags", "email_receipts", "pending_receipt_matches",
    "account_sign_conventions", "amazon_login_profiles", "amazon_orders",
    "amazon_items",
]


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_tenant_columns_exist(tmp_path):
    db = _create_db(tmp_path)
    insp = sa.inspect(db._engine)
    for table in OWNER_VIS_TABLES:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert {"household_id", "owner_user_id", "visibility"} <= cols, table
    plaid_items_cols = {c["name"] for c in insp.get_columns("plaid_items")}
    assert {"household_id", "owner_user_id"} <= plaid_items_cols
    assert "visibility" not in plaid_items_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_columns_present.py -v`
Expected: FAIL — `AssertionError` (columns missing).

- [ ] **Step 3: Write minimal implementation**

In `models.py`, add to each owner/visibility model:

```python
    household_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String, nullable=True)
```

(omit `visibility` for `PlaidItem`; add `household_id` + `owner_user_id` there).
Add only `household_id` to `Tag` and `TransactionCategoryEvent`.

Create `008_add_tenant_columns_nullable.py` (revision
`008_add_tenant_columns_nullable`, `down_revision =
"007_revive_plaid_accounts"`):

```python
import sqlalchemy as sa
from alembic import op

revision = "008_add_tenant_columns_nullable"
down_revision = "007_revive_plaid_accounts"
branch_labels = None
depends_on = None

OWNER_VIS = [
    "plaid_transactions", "derived_transactions", "transaction_items",
    "transaction_tags", "email_receipts", "pending_receipt_matches",
    "account_sign_conventions", "amazon_login_profiles", "amazon_orders",
    "amazon_items",
]
HOUSEHOLD_ONLY = ["tags", "transaction_category_events"]


def upgrade() -> None:
    for t in OWNER_VIS:
        op.add_column(t, sa.Column("household_id", sa.Uuid(), nullable=True))
        op.add_column(t, sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        op.add_column(t, sa.Column("visibility", sa.String(), nullable=True))
    op.add_column("plaid_items", sa.Column("household_id", sa.Uuid(), nullable=True))
    op.add_column("plaid_items", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    for t in HOUSEHOLD_ONLY:
        op.add_column(t, sa.Column("household_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    for t in HOUSEHOLD_ONLY:
        op.drop_column(t, "household_id")
    op.drop_column("plaid_items", "owner_user_id")
    op.drop_column("plaid_items", "household_id")
    for t in OWNER_VIS:
        op.drop_column(t, "visibility")
        op.drop_column(t, "owner_user_id")
        op.drop_column(t, "household_id")
```

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_columns_present.py -v` → PASS.
Run: `cd backend && DATABASE_URL="sqlite:///$(mktemp -u).db" uv run alembic upgrade head` → ends at `008`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py \
  backend/db/migrations/008_add_tenant_columns_nullable.py \
  backend/tests/adapters/db/test_tenant_columns_present.py
git commit -m "feat(db): add nullable tenant columns to financial tables (migration 008)"
```

---

### Task 6: Backfill existing data + migration 009

A **data-only** migration for **dev/test only** — it does **not** run on prod.
The migration body is a no-op unless the explicit opt-in env
`PENNY_DEV_BACKFILL=1` is set; when set (local/CI), it creates a dev household +
two users, populates `plaid_accounts` from distinct
`plaid_transactions.account_id` (+ their `item_id`), and backfills every tenant
column to that household / user1 / `visibility='private'` so the contract
migration (010) can apply on a populated dev DB. Idempotent (guards on existing
rows / null columns).

> **Prod ownership belongs to the cutover, not this migration.** Migration 009
> never hardcodes a specific household's identity on prod. On prod the
> [Phase-3 cutover](../specs/2026-07-03-phase-3-cutover-design.md) applies the
> chain in two halves — expand (006–009, with 009 a no-op) → **interactive
> account assignment + re-parent** → contract (010–013) — so legacy rows are
> assigned real owners/visibility *before* the NOT-NULL/RLS contract lands.
> This is the single-source-of-truth fix: exactly one mechanism (the cutover)
> creates prod identity and assigns ownership.

**Files:**
- Create: `backend/db/migrations/009_backfill_tenant_columns.py`
- Test: `backend/tests/adapters/db/test_backfill_migration.py`

**Interfaces:**
- Consumes: env `PENNY_DEV_HOUSEHOLD_ID`, `PENNY_DEV_USER_ID`,
  `PENNY_DEV_USER2_ID` (the second user), `PENNY_DEV_USER_EMAIL`,
  `PENNY_DEV_USER2_EMAIL`.
- Produces: no NULL tenant columns remain for existing data; one
  `plaid_accounts` row per distinct account_id.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_backfill_migration.py
import uuid
from pathlib import Path

import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import PlaidItem, PlaidTransaction
from penny.db_backfill import backfill_household  # helper the migration calls

H = uuid.UUID("22222222-2222-2222-2222-222222222222")
U1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
U2 = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _seed(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add(PlaidItem(item_id="item-1", access_token="tok"))
        s.flush()
        s.add(PlaidTransaction(
            external_id="e1", source="PLAID", account_id="acct-1", item_id="item-1",
            posted_at=sa.func.current_date(), amount_cents=100, currency="USD",
        ))
    return db


def test_backfill_assigns_household_and_creates_accounts(tmp_path):
    db = _seed(tmp_path)
    with db.session() as s:
        backfill_household(
            s, household_id=H, name="Bossy",
            user1=(U1, "adam@example.com"), user2=(U2, "wife@example.com"),
        )
    with db.session() as s:
        txn = s.query(PlaidTransaction).filter_by(external_id="e1").one()
        assert txn.household_id == H
        assert txn.owner_user_id == U1
        assert txn.visibility == "private"
        accts = s.execute(sa.text("SELECT account_id, visibility FROM plaid_accounts")).all()
        assert ("acct-1", "private") in [(a[0], a[1]) for a in accts]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_backfill_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.db_backfill'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/penny/db_backfill.py` with a `backfill_household(session, *,
household_id, name, user1, user2)` function that: inserts the household + two
users if missing; inserts a `plaid_accounts` row for each distinct
`(account_id, item_id)` in `plaid_transactions` (owner = user1, visibility
`'private'`); then `UPDATE`s every owner/visibility table setting
`household_id`, `owner_user_id=user1`, `visibility='private'` where NULL, and
sets `household_id` on `plaid_items`, `tags`, `transaction_category_events`.
Use parameterized `sa.text(...)` statements. Then create
`009_backfill_tenant_columns.py` whose `upgrade()` reads the env ids and calls
`backfill_household(op.get_bind()…)` inside a `Session(bind=op.get_bind())`.
`downgrade()` is a no-op (`pass`) — data migrations don't reverse.

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/adapters/db/test_backfill_migration.py -v` → PASS.
Run the chain with env set:
```bash
cd backend && PENNY_DEV_HOUSEHOLD_ID=22222222-2222-2222-2222-222222222222 \
  PENNY_DEV_USER_ID=11111111-1111-1111-1111-111111111111 \
  PENNY_DEV_USER2_ID=33333333-3333-3333-3333-333333333333 \
  PENNY_DEV_USER_EMAIL=adam@example.com PENNY_DEV_USER2_EMAIL=wife@example.com \
  DATABASE_URL="sqlite:///$(mktemp -u).db" uv run alembic upgrade head
```
Expected: ends at `009`, no error.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/db_backfill.py \
  backend/db/migrations/009_backfill_tenant_columns.py \
  backend/tests/adapters/db/test_backfill_migration.py
git commit -m "feat(db): backfill existing data to household + create plaid_accounts (migration 009)"
```

---

### Task 7: Contract — NOT NULL, FKs, indexes + migration 010

Tightens the columns added in 008 now that 009 has populated them. Sets
`NOT NULL`, adds FKs (`household_id`→households, `owner_user_id`→users), a
`CHECK (visibility IN ('private','shared'))`, and composite indexes
`(household_id, owner_user_id)` on the hot tables. Update the ORM column types
back to non-optional (`Mapped[uuid.UUID]`, `Mapped[str]`) for the now-required
columns.

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (drop `| None` on the required
  tenant columns)
- Create: `backend/db/migrations/010_tenant_columns_not_null_and_fks.py`
- Test: `backend/tests/adapters/db/test_tenant_constraints.py`

**Interfaces:**
- Produces: tenant columns are `NOT NULL` with FKs + visibility CHECK; an insert
  missing `household_id` fails.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_tenant_constraints.py
from pathlib import Path

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.models import PlaidItem, PlaidTransaction


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}", enforce_sqlite_fks=True)
    db.create_schema()
    return db


def test_household_id_required(tmp_path):
    db = _create_db(tmp_path)
    with pytest.raises(sa.exc.IntegrityError):
        with db.session() as s:
            s.add(PlaidItem(item_id="i", access_token="t"))  # no household_id
            s.flush()
```

> Note: when `create_schema()` builds a fresh DB from current models the columns
> are already `NOT NULL`, so this test validates the *model* end state; the
> migration test below validates the upgrade path on a populated DB.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_constraints.py -v`
Expected: FAIL (insert succeeds because columns still nullable).

- [ ] **Step 3: Write minimal implementation**

In `models.py`, change the required tenant columns to non-optional and add the
CHECK on owner/visibility tables, e.g. for `PlaidTransaction`:

```python
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("households.household_id"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.user_id"), nullable=False
    )
    visibility: Mapped[str] = mapped_column(String, nullable=False)
```

Create `010_tenant_columns_not_null_and_fks.py` (revision
`010_…`, `down_revision = "009_backfill_tenant_columns"`). Because SQLite cannot
`ALTER COLUMN`, wrap NOT-NULL/FK/CHECK changes in `op.batch_alter_table(t) as
batch:` (Alembic's batch mode recreates the table on SQLite and emits plain
`ALTER` on Postgres). For each owner/visibility table set the three columns
`nullable=False`, add `batch.create_foreign_key(...)` for household_id and
owner_user_id, add `batch.create_check_constraint("ck_%s_visibility" % t,
"visibility IN ('private','shared')")`, and
`op.create_index("ix_%s_household_owner" % t, t, ["household_id",
"owner_user_id"])`. `downgrade()` reverses (drop indexes/constraints, set
nullable True).

- [ ] **Step 4: Run test + full-chain migration check on a populated DB**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_constraints.py -v` → PASS.
Run the env-seeded chain from Task 6 Step 4 again → ends at `010`, no error
(this exercises expand→backfill→contract end to end on SQLite).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py \
  backend/db/migrations/010_tenant_columns_not_null_and_fks.py \
  backend/tests/adapters/db/test_tenant_constraints.py
git commit -m "feat(db): tighten tenant columns to NOT NULL + FKs + checks (migration 010)"
```

---

### Task 8: Façade session plumbing — `SET LOCAL` + write-time denorm

The `session()` context manager reads the current `RequestContext` and, on
Postgres, emits `SET LOCAL app.current_household` / `app.current_user` (using
`effective_user_id`, so joint mode sends the nil sentinel). A new
`session_for(ctx)` helper sets the ContextVar for non-request callers (cron,
scripts). Write-time population of denormalized columns is covered by app
filtering in Task 9; this task is the connection binding.

**Files:**
- Modify: `backend/penny/adapters/db/facade.py` (the `session()` CM)
- Test: `backend/tests/adapters/db/test_session_set_local.py`

**Interfaces:**
- Consumes: `get_request_context`, `effective_user_id` from `penny.tenancy`.
- Produces: `DB.session()` unchanged signature; emits `SET LOCAL` on Postgres
  when a context is set. `DB.session_for(ctx: RequestContext)` context manager.

- [ ] **Step 1: Write the failing test** (SQLite path — asserts no crash + a spy)

```python
# backend/tests/adapters/db/test_session_set_local.py
import uuid
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.tenancy.context import RequestContext, SessionMode, set_request_context, reset_request_context


def _db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_session_runs_with_context_on_sqlite_noop(tmp_path):
    # On SQLite, SET LOCAL must be skipped (no error).
    db = _db(tmp_path)
    ctx = RequestContext(
        user_id=uuid.uuid4(), household_id=uuid.uuid4(), session_mode=SessionMode.JOINT
    )
    token = set_request_context(ctx)
    try:
        with db.session() as s:
            s.execute(__import__("sqlalchemy").text("SELECT 1"))
    finally:
        reset_request_context(token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_session_set_local.py -v`
Expected: at this point it may PASS trivially; add the Postgres assertion in the
RLS task. (If `session_for` is referenced elsewhere first, FAIL on import.)

- [ ] **Step 3: Write minimal implementation**

Modify `facade.py`'s `session()`:

```python
@contextmanager
def session(self) -> Iterator[Session]:
    session = self._session_factory()
    try:
        self._apply_rls_settings(session)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def _apply_rls_settings(self, session: Session) -> None:
    if self._engine.dialect.name != "postgresql":
        return
    from penny.tenancy.context import effective_user_id, get_request_context
    ctx = get_request_context()
    if ctx is None:
        return
    session.execute(
        text("SELECT set_config('app.current_household', :h, true), "
             "set_config('app.current_user', :u, true)"),
        {"h": str(ctx.household_id), "u": str(effective_user_id(ctx))},
    )

@contextmanager
def session_for(self, ctx: "RequestContext") -> Iterator[Session]:
    from penny.tenancy.context import reset_request_context, set_request_context
    token = set_request_context(ctx)
    try:
        with self.session() as s:
            yield s
    finally:
        reset_request_context(token)
```

(`set_config(..., true)` is the transaction-local form of `SET LOCAL` and accepts
a bound parameter, unlike `SET LOCAL`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/adapters/db/test_session_set_local.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/facade.py \
  backend/tests/adapters/db/test_session_set_local.py
git commit -m "feat(db): session() applies transaction-local RLS settings on Postgres"
```

---

### Task 9: Façade app-level filtering (the suspenders)

Add `household_id`/visibility predicates to the read methods that return
financial rows, and populate denormalized columns on the write paths. Use a
shared helper so it's DRY.

**Files:**
- Modify: `backend/penny/adapters/db/facade.py`
- Test: `backend/tests/adapters/db/test_tenant_scoping.py`

**Interfaces:**
- Consumes: `require_request_context`, `effective_user_id`, `SessionMode`.
- Produces: a module-level helper
  `visible_filter(model, ctx)` returning a SQLAlchemy boolean clause:
  `model.household_id == ctx.household_id AND (model.owner_user_id ==
  ctx.user_id OR model.visibility == 'shared')` — and for joint mode just
  `model.household_id == ctx.household_id AND model.visibility == 'shared'`.
  Read methods that list/fetch transactions apply it.

- [ ] **Step 1: Write the failing test** (SQLite — app filter works without RLS)

```python
# backend/tests/adapters/db/test_tenant_scoping.py
import uuid
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidAccount, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import RequestContext, SessionMode

H = uuid.uuid4(); U1 = uuid.uuid4(); U2 = uuid.uuid4()


def _seed(tmp_path):
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add(Household(household_id=H, name="Bossy")); s.flush()
        s.add_all([
            User(user_id=U1, household_id=H, email="a@x.com"),
            User(user_id=U2, household_id=H, email="b@x.com"),
            PlaidItem(item_id="i1", access_token="t", household_id=H, owner_user_id=U1),
        ]); s.flush()
        # one private (U2) and one shared transaction
        for ext, owner, vis in [("priv", U2, "private"), ("shar", U1, "shared")]:
            s.add(PlaidTransaction(
                external_id=ext, source="PLAID", account_id="acct", item_id="i1",
                posted_at=__import__("datetime").date(2026, 1, 1), amount_cents=1,
                currency="USD", household_id=H, owner_user_id=owner, visibility=vis,
            ))
    return db


def test_individual_sees_own_private_plus_shared(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H)
    with db.session_for(ctx) as s:
        rows = db.list_visible_plaid_transactions(s)
        exts = {r.external_id for r in rows}
    assert exts == {"shar"}  # U1 sees shared; U2's private is hidden


def test_joint_sees_shared_only(tmp_path):
    db = _seed(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H, session_mode=SessionMode.JOINT)
    with db.session_for(ctx) as s:
        rows = db.list_visible_plaid_transactions(s)
        exts = {r.external_id for r in rows}
    assert exts == {"shar"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_scoping.py -v`
Expected: FAIL — `AttributeError: 'DB' object has no attribute 'list_visible_plaid_transactions'`.

- [ ] **Step 3: Write minimal implementation**

Add to `facade.py`:

```python
def visible_filter(model: Any, ctx: "RequestContext"):
    from penny.tenancy.context import SessionMode
    base = model.household_id == ctx.household_id
    if ctx.session_mode is SessionMode.JOINT:
        return sa.and_(base, model.visibility == "shared")
    return sa.and_(
        base,
        sa.or_(model.owner_user_id == ctx.user_id, model.visibility == "shared"),
    )
```

```python
def list_visible_plaid_transactions(self, session: Session) -> list[PlaidTransaction]:
    from penny.tenancy.context import require_request_context
    ctx = require_request_context()
    rows = session.query(PlaidTransaction).filter(
        visible_filter(PlaidTransaction, ctx)
    ).all()
    for r in rows:
        session.expunge(r)
    return rows
```

Then apply `visible_filter(...)` inside the existing list/fetch methods that
return financial rows (e.g. `list_plaid_transactions_in_date_range`,
`fetch_transactions_by_ids_preserving_order`, the derived-transaction listers).
Populate `household_id`/`owner_user_id`/`visibility` on insert paths by copying
from the row's `plaid_accounts` record (look up by `account_id`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/adapters/db/test_tenant_scoping.py -v` → PASS (2 passed).
Run the whole suite: `cd backend && uv run pytest -q` → green (fix any existing
façade tests that now need a `RequestContext`; wrap them in `db.session_for(ctx)`).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/facade.py \
  backend/tests/adapters/db/test_tenant_scoping.py
git commit -m "feat(db): app-level visibility filtering on financial reads"
```

---

### Task 10: RLS policies + migration 011 (Postgres-only) + the `pg_db` fixture

Creates the Postgres RLS policies and the `@pytest.mark.postgres` test path.

**Files:**
- Create: `backend/db/migrations/011_enable_rls_policies.py`
- Create: `backend/tests/conftest_postgres.py` (the `pg_db` fixture)
- Modify: `backend/pyproject.toml` (register the `postgres` marker)
- Create: `backend/tests/adapters/db/test_rls_isolation.py`

**Interfaces:**
- Consumes: the denormalized columns + `session_for`.
- Produces: RLS enabled on every owner/visibility + household-only table with a
  policy named `tenant_isolation`; a `pg_db` pytest fixture yielding a `DB`
  bound to `POSTGRES_TEST_URL` with the schema migrated, auto-skipping when the
  env var is unset.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_rls_isolation.py
import datetime
import uuid

import pytest

from penny.adapters.db.models import Household, PlaidItem, PlaidTransaction, User
from penny.tenancy.context import RequestContext, SessionMode

pytestmark = pytest.mark.postgres

HA, HB = uuid.uuid4(), uuid.uuid4()
UA, UB = uuid.uuid4(), uuid.uuid4()


def _seed(db):
    # bypass RLS for seeding via a superuser/no-context session
    with db.session() as s:
        s.add_all([Household(household_id=HA, name="A"), Household(household_id=HB, name="B")]); s.flush()
        s.add_all([
            User(user_id=UA, household_id=HA, email="a@x.com"),
            User(user_id=UB, household_id=HB, email="b@x.com"),
            PlaidItem(item_id="ia", access_token="t", household_id=HA, owner_user_id=UA),
            PlaidItem(item_id="ib", access_token="t", household_id=HB, owner_user_id=UB),
        ]); s.flush()
        s.add_all([
            PlaidTransaction(external_id="ta", source="PLAID", account_id="aa", item_id="ia",
                posted_at=datetime.date(2026,1,1), amount_cents=1, currency="USD",
                household_id=HA, owner_user_id=UA, visibility="private"),
            PlaidTransaction(external_id="tb", source="PLAID", account_id="ab", item_id="ib",
                posted_at=datetime.date(2026,1,1), amount_cents=1, currency="USD",
                household_id=HB, owner_user_id=UB, visibility="private"),
        ])


def test_household_a_cannot_see_household_b_even_via_raw_sql(pg_db):
    _seed(pg_db)
    ctx = RequestContext(user_id=UA, household_id=HA)
    with pg_db.session_for(ctx) as s:
        import sqlalchemy as sa
        rows = s.execute(sa.text("SELECT external_id FROM plaid_transactions")).all()
    assert {r[0] for r in rows} == {"ta"}  # RLS hides B entirely, even from raw SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_rls_isolation.py -v`
Expected: FAIL — no `pg_db` fixture / RLS not enabled (B rows visible).
Without `POSTGRES_TEST_URL`: the test is **skipped**.

- [ ] **Step 3: Write minimal implementation**

Register the marker in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "postgres: requires a Postgres database (set POSTGRES_TEST_URL); skipped otherwise",
]
```

Create `backend/tests/conftest_postgres.py`:

```python
import os
import uuid

import pytest

from penny.adapters.db.facade import DB


@pytest.fixture
def pg_db():
    url = os.environ.get("POSTGRES_TEST_URL", "").strip()
    if not url:
        pytest.skip("POSTGRES_TEST_URL not set")
    # unique schema per test for isolation
    schema = f"t_{uuid.uuid4().hex[:8]}"
    admin = DB(url)
    with admin.session() as s:
        import sqlalchemy as sa
        s.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    db = DB(f"{url}?options=-csearch_path%3D{schema}")
    db.create_schema()
    _apply_rls(db)  # run the policy DDL from migration 011 against this schema
    yield db
    with admin.session() as s:
        import sqlalchemy as sa
        s.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
```

(`conftest_postgres.py` is auto-collected because pytest imports every
`conftest*.py`; alternatively import its fixture from the package `conftest.py`.)

Create `011_enable_rls_policies.py` (revision `011_…`, `down_revision =
"010_tenant_columns_not_null_and_fks"`) guarded on Postgres:

```python
from alembic import op

revision = "011_enable_rls_policies"
down_revision = "010_tenant_columns_not_null_and_fks"
branch_labels = None
depends_on = None

OWNER_VIS = [ ... ]      # same list as migration 008
HOUSEHOLD_ONLY = ["tags", "transaction_category_events", "categories"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for t in OWNER_VIS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {t} USING (
              household_id = current_setting('app.current_household', true)::uuid
              AND (owner_user_id = current_setting('app.current_user', true)::uuid
                   OR visibility = 'shared')
            )""")
    for t in HOUSEHOLD_ONLY:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {t} USING (
              household_id = current_setting('app.current_household', true)::uuid
            )""")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for t in OWNER_VIS + HOUSEHOLD_ONLY:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
```

The `_apply_rls(db)` helper in the fixture runs the same `CREATE POLICY` block
(import and call the migration's `upgrade()` against the test schema bind, or
factor the DDL into a shared function `rls_ddl(bind)` the migration also calls).

> Seeding caveat: `FORCE ROW LEVEL SECURITY` applies even to the table owner, so
> the `_seed` helper must run with a `RequestContext` per household (seed A's
> rows under HA's context, B's under HB's), or temporarily as a role that
> bypasses RLS. The fixture documents this; the test seeds each household under
> its own context.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_rls_isolation.py -v` → PASS.
Run without the env var → SKIPPED. Run full suite `uv run pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add backend/db/migrations/011_enable_rls_policies.py \
  backend/tests/conftest_postgres.py backend/pyproject.toml \
  backend/tests/adapters/db/test_rls_isolation.py
git commit -m "feat(db): enable RLS policies + postgres-marked isolation tests (migration 011)"
```

---

### Task 11: Wire `RequestContext` into the request + agent path

**Files:**
- Modify: `backend/penny/api/main.py` (build + set context in `/api/chat`)
- Modify: `backend/penny/agent_factory.py` (accept `RequestContext`, scope memory)
- Test: `backend/tests/api/test_chat_sets_context.py`

**Interfaces:**
- Consumes: `resolve_dev_principal`, `set_request_context`, `reset_request_context`.
- Produces: `build_agent(*, model, session, persist_session=True, ctx:
  RequestContext)` — new required keyword; `_render_system_prompt(ctx)` filters
  `{{AGENT_MEMORY}}` by `ctx` (own-private + shared, or shared-only when joint).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_chat_sets_context.py
import uuid

from penny.tenancy.principal import resolve_dev_principal
from penny.tenancy.context import SessionMode


def test_request_headers_build_joint_context():
    ctx = resolve_dev_principal({
        "X-Penny-User-Id": str(uuid.uuid4()),
        "X-Penny-Household-Id": str(uuid.uuid4()),
        "X-Penny-Session-Mode": "joint",
    })
    assert ctx.session_mode is SessionMode.JOINT
```

(Full handler wiring is integration-tested; this unit test pins the header
contract the handler relies on.)

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `cd backend && uv run pytest tests/api/test_chat_sets_context.py -v`
Expected: PASS (depends only on Task 2). The behavioral change is the handler
edit below — verify manually in Step 4.

- [ ] **Step 3: Write minimal implementation**

In `api/main.py` `chat()` handler, before `_seed_session(...)`:

```python
from penny.tenancy.context import reset_request_context, set_request_context
from penny.tenancy.principal import resolve_dev_principal

ctx = resolve_dev_principal(dict(request.headers))
token = set_request_context(ctx)
```

Pass `ctx=ctx` to `build_agent(...)`, and ensure the streaming generator resets
the context when done (wrap `stream_and_persist` so `reset_request_context(token)`
runs in a `finally`). In `agent_factory.build_agent`, add the `ctx` keyword and
thread it into `_render_system_prompt(ctx)`; `_assemble_agent_memory` filters by
`ctx` (until phase 1b moves memory to the hybrid store, filter the per-household
filesystem memory dir by the requesting user's visibility / session mode).

- [ ] **Step 4: Verify**

Run: `cd backend && uv run pytest -q` → green.
Manual: start the server with `PENNY_DEV_USER_ID` / `PENNY_DEV_HOUSEHOLD_ID` set
and POST `/api/chat`; confirm a request without those (and no headers) returns a
clear 400/500 from the `ValueError`, and a request with them succeeds.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/api/main.py backend/penny/agent_factory.py \
  backend/tests/api/test_chat_sets_context.py
git commit -m "feat(api): resolve and set RequestContext per /api/chat request"
```

---

### Task 12: Taxonomy per-household + migration 012

`categories` gets `household_id`; seeding becomes per-household; existing
categories backfill to your household.

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (`Category.household_id`)
- Create: `backend/db/migrations/012_add_household_id_to_categories.py`
- Modify: `backend/penny/bootstrap.py` (seed taxonomy for a given household)
- Test: `backend/tests/test_taxonomy_per_household.py`

**Interfaces:**
- Produces: `Category.household_id: Mapped[uuid.UUID]` (FK→households); a
  `seed_taxonomy_for_household(session, household_id)` function in `bootstrap.py`
  that seeds from `configs/taxonomy.yaml` scoped to that household. The active
  unique index becomes `(household_id, key)` where `deprecated_at IS NULL`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_taxonomy_per_household.py
import uuid
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, Household
from penny.bootstrap import seed_taxonomy_for_household

H1 = uuid.uuid4(); H2 = uuid.uuid4()


def test_two_households_get_independent_taxonomies(tmp_path):
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add_all([Household(household_id=H1, name="A"), Household(household_id=H2, name="B")]); s.flush()
        seed_taxonomy_for_household(s, H1)
        seed_taxonomy_for_household(s, H2)
    with db.session() as s:
        n1 = s.query(Category).filter_by(household_id=H1).count()
        n2 = s.query(Category).filter_by(household_id=H2).count()
    assert n1 > 0 and n1 == n2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_taxonomy_per_household.py -v`
Expected: FAIL — `ImportError`/`AttributeError` (`household_id` / function absent).

- [ ] **Step 3: Write minimal implementation**

Add `household_id: Mapped[uuid.UUID] = mapped_column(Uuid,
ForeignKey("households.household_id"), nullable=False)` to `Category`; change the
unique index to include `household_id`. Migration `012` adds the column
(nullable → backfill existing rows to `PENNY_DEV_HOUSEHOLD_ID` → NOT NULL via
`batch_alter_table`), drops/recreates the unique index as `(household_id, key)
WHERE deprecated_at IS NULL`. Refactor `bootstrap.py`'s existing seed loop into
`seed_taxonomy_for_household(session, household_id)` (parents then children, as
today) and call it for the dev household at startup.

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/test_taxonomy_per_household.py -v` → PASS.
Run the env-seeded chain → ends at `012`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/penny/bootstrap.py \
  backend/db/migrations/012_add_household_id_to_categories.py \
  backend/tests/test_taxonomy_per_household.py
git commit -m "feat(db): per-household taxonomy (migration 012)"
```

---

### Task 13: Plaid token encryption + migration 013

Encrypt `plaid_items.access_token` at rest with Fernet; decrypt only at the
Plaid call site.

**Files:**
- Create: `backend/penny/security/__init__.py`,
  `backend/penny/security/token_cipher.py`
- Create: `backend/db/migrations/013_encrypt_plaid_access_tokens.py`
- Modify: the Plaid client call site that reads `access_token` (in
  `tools/_services` sync / `adapters/clients`) to decrypt on use, and the
  persister that writes it to encrypt on write
- Modify: `backend/pyproject.toml` (add `cryptography`), `backend/.env.example`
- Test: `backend/tests/security/test_token_cipher.py`

**Interfaces:**
- Produces:
  - `encrypt_token(plaintext: str) -> str` and `decrypt_token(ciphertext: str)
    -> str` reading the Fernet key from `PENNY_PLAID_TOKEN_KEY`.
  - **Key-version prefix (per the migration ledger):** stored ciphertext is
    prefixed with a key id, e.g. `v1:<fernet-token>`. `encrypt_token` writes the
    active key's prefix; `decrypt_token` reads the prefix and selects the key.
    No rotation *logic* is built now — but stamping the format now means rotation
    later is not a re-encrypt-everything migration. `is_encrypted(value)` matches
    the `v<N>:` prefix (falling back to the Fernet `gAAAAA` sniff for any
    unprefixed legacy value) so the migration/read path stay idempotent.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/security/test_token_cipher.py
from cryptography.fernet import Fernet

from penny.security.token_cipher import decrypt_token, encrypt_token, is_encrypted


def test_round_trip(monkeypatch):
    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    ct = encrypt_token("access-sandbox-123")
    assert ct != "access-sandbox-123"
    assert is_encrypted(ct)
    assert decrypt_token(ct) == "access-sandbox-123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/security/test_token_cipher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.security'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/security/token_cipher.py
from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _cipher() -> Fernet:
    key = os.environ.get("PENNY_PLAID_TOKEN_KEY", "").strip()
    if not key:
        raise RuntimeError("PENNY_PLAID_TOKEN_KEY is not set")
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _cipher().decrypt(ciphertext.encode()).decode()


def is_encrypted(value: str) -> bool:
    return value.startswith("gAAAAA")
```

Add `cryptography` to `pyproject.toml` deps; document `PENNY_PLAID_TOKEN_KEY` in
`.env.example`. In the write path (`PlaidItem` persistence), call
`encrypt_token` if `not is_encrypted(...)`; in the read path (where the Plaid
client uses `access_token`), call `decrypt_token`. Migration `013` is data-only:
for each `plaid_items` row, if `not is_encrypted(access_token)`, set it to
`encrypt_token(access_token)`. `downgrade()` decrypts.

- [ ] **Step 4: Run test + migration check**

Run: `cd backend && uv run pytest tests/security/test_token_cipher.py -v` → PASS.
Run with key set:
`cd backend && PENNY_PLAID_TOKEN_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") DATABASE_URL="sqlite:///$(mktemp -u).db" uv run alembic upgrade head`
→ ends at `013`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/security backend/pyproject.toml backend/.env.example \
  backend/db/migrations/013_encrypt_plaid_access_tokens.py \
  backend/tests/security/test_token_cipher.py
git commit -m "feat(security): encrypt plaid access tokens at rest (migration 013)"
```

---

### Task 14: Integration leakage / privacy / joint suites + docs

A consolidated Postgres-marked suite asserting the spec's guarantees end to end,
plus a README note on running the Postgres suite.

**Files:**
- Create: `backend/tests/adapters/db/test_multitenant_acceptance.py` (Postgres-marked)
- Modify: `AGENTS.md` (a line on `POSTGRES_TEST_URL` for the RLS suite)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_multitenant_acceptance.py
import pytest

pytestmark = pytest.mark.postgres

# Battery (each seeds two households A/B and asserts isolation):
# 1. test_run_sql_select_star_returns_only_own_household
# 2. test_within_household_private_account_hidden_from_spouse
# 3. test_shared_account_visible_to_both_spouses
# 4. test_joint_session_sees_shared_only
# 5. test_write_cannot_set_foreign_household_id (RLS WITH CHECK rejects it)
```

> Implement each as a concrete test mirroring Task 10's seed/query pattern with
> explicit assertions (no placeholders): seed A+B under their own contexts, then
> assert the visible set from each context. Test 5 confirms the policies include
> a `WITH CHECK` clause — add `WITH CHECK (...)` to the migration 011 policies if
> not already present so a tenant cannot INSERT/UPDATE a row into another
> household.

- [ ] **Step 2–4: Run, implement, verify**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_multitenant_acceptance.py -v`.
Iterate (TDD) until all five pass; add `WITH CHECK` to the policies in migration
011 if test 5 fails. Confirm `uv run pytest -q` is green and the suite skips
without the env var.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/adapters/db/test_multitenant_acceptance.py AGENTS.md
git commit -m "test: multi-tenant acceptance suite (cross-household, privacy, joint, write-check)"
```

---

## Browser E2E Validation (Playwright)

The unit/integration suites above prove tenancy at the DB seam. These two tasks
prove the *whole app* — real backend + real vite frontend + a real headless
browser — still works under the tenancy layer, and stand up the Playwright
harness that every later phase reuses. Phase 1a **owns** the harness bootstrap;
later phases only add feature specs (and a Clerk-test-sign-in helper) on top of
it.

### Task 15: Playwright harness bootstrap (this phase owns it)

Stand up `@playwright/test` in the frontend with a config and a fixture that
boots the backend in `PENNY_AUTH_MODE=dev` with an env-pinned dev principal plus
the vite frontend, so specs run against a live app in headless CI. No feature
assertions yet — the deliverable is a green trivial spec proving the harness
launches both servers and drives a browser.

**Files:**
- Modify: `frontend/package.json` (add `@playwright/test` devDependency + an
  `e2e` script), `frontend/.gitignore` (ignore `playwright-report/`,
  `test-results/`).
- Create: `frontend/playwright.config.ts` — headless, `use.baseURL` pointing at
  the vite dev server (`http://127.0.0.1:5173`), a `webServer` (or global-setup)
  block that starts backend + frontend, single project (chromium), CI-friendly
  (`forbidOnly: !!process.env.CI`, retries on CI).
- Create: `frontend/e2e/fixtures/app.ts` — a `test` fixture extending
  `@playwright/test` that ensures the backend is up in
  `PENNY_AUTH_MODE=dev` with `PENNY_DEV_USER_ID` / `PENNY_DEV_HOUSEHOLD_ID`
  (and `PENNY_DEV_SESSION_MODE=individual`) pinned to a seeded dev household, and
  exposes helpers later phases extend. (A `signInWithClerkTestToken` helper is
  **added by a later phase** — leave a documented stub/TODO here, do not
  implement Clerk auth in phase 1a.)
- Create: `frontend/e2e/harness.spec.ts` — trivial spec: navigate to `/`, assert
  the document has a title / the app root renders.

**Interfaces:**
- Produces: a reusable `test`/`expect` export from `e2e/fixtures/app.ts`; a
  `webServer` config that boots `uvicorn penny.api.main:app` (with the dev env
  vars) and `npm run dev`; `npm run e2e` → `playwright test`.

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/harness.spec.ts
import { test, expect } from "./fixtures/app";

test("app harness boots and serves the SPA", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Penny/i);
  await expect(page.locator("#root")).toBeVisible();
});
```

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/harness.spec.ts`
Expected: FAIL — `@playwright/test` not installed / no `playwright.config.ts` /
`Cannot find module './fixtures/app'`.

- [ ] **Step 3: Implement the harness**

Install and scaffold:

```bash
cd frontend && npm install -D @playwright/test && npx playwright install --with-deps chromium
```

Write `frontend/playwright.config.ts` with `use: { baseURL:
"http://127.0.0.1:5173" }`, `fullyParallel: false`, and a `webServer` array that
launches (a) the backend with `PENNY_AUTH_MODE=dev`,
`PENNY_DEV_USER_ID`/`PENNY_DEV_HOUSEHOLD_ID` set to a seeded dev household, and
`DATABASE_URL` on a throwaway SQLite/Postgres test db, and (b) `npm run dev`,
each with `reuseExistingServer: !process.env.CI` and a `url` health check.
Write `frontend/e2e/fixtures/app.ts` re-exporting `test`/`expect` (extend later),
with a documented `// TODO(phase 2+): signInWithClerkTestToken(page)` stub.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/harness.spec.ts`
Expected: PASS (1 passed) — both servers boot, the SPA renders headless.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/.gitignore \
  frontend/playwright.config.ts frontend/e2e/fixtures/app.ts \
  frontend/e2e/harness.spec.ts
git commit -m "test(e2e): bootstrap Playwright harness (dev-mode backend + vite, headless)"
```

---

### Task 16: Chat smoke E2E — the tenancy layer didn't break the app

An end-to-end spec that loads the app, sends a chat message, and asserts a
streamed assistant response renders — proving the phase-1a tenancy/RLS layer
left the loading → sending → streaming flow intact through the real UI.

**Files:**
- Create: `frontend/e2e/chat-smoke.spec.ts`

**Interfaces:**
- Consumes: the `test` fixture from Task 15 (dev principal already pinned).

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/chat-smoke.spec.ts
import { test, expect } from "./fixtures/app";

test("user sends a chat message and an assistant response streams in", async ({ page }) => {
  await page.goto("/");
  const composer = page.getByRole("textbox");
  await composer.fill("Hello Penny, are you there?");
  await composer.press("Enter");

  // user message shows immediately
  await expect(page.getByText("Hello Penny, are you there?")).toBeVisible();

  // an assistant message streams in and ends up non-empty
  const assistant = page.locator('[data-role="assistant"]').last();
  await expect(assistant).toBeVisible({ timeout: 30_000 });
  await expect(assistant).not.toBeEmpty();
});
```

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/chat-smoke.spec.ts`
Expected: FAIL initially — selectors (`[data-role="assistant"]`) may need
aligning with the rendered `Message` markup; adjust the locators to the actual
agent-ui DOM (add a `data-role`/`data-testid` in `ChatScreen` if none exists).

- [ ] **Step 3: Make it pass**

Run the app locally, inspect the message DOM, and pin the spec to stable
selectors (prefer a `data-testid` on the message list + `data-role` on each
message; add them to `ChatScreen`/the agent-ui usage if absent). Keep the
backend in dev mode with a real (or recorded) model so a response actually
streams; if the CI model key is absent, gate this spec behind a
`test.skip(!process.env.PENNY_E2E_MODEL)` guard documented in the spec.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/chat-smoke.spec.ts`
Expected: PASS (1 passed) — message sent, assistant response rendered end to end.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/chat-smoke.spec.ts frontend/src
git commit -m "test(e2e): chat smoke spec proves tenancy layer keeps chat working end to end"
```

---

### Task 17: CI regression job (stand it up here; every later phase adds to it)

**Why here:** Phase 1a owns the first isolation suites and the Playwright
harness. The standing CI gate must exist from the *first* phase that touches RLS
— not be introduced at Phase 6 — so no later phase can silently regress an
isolation guarantee, and so Phase 3 never ships real data before a guard exists.
Phase 6 later *hardens* this job (adds the policy-lint, dep-scan, alembic drift
check, and the blocking-gate discipline); it does not create CI from zero.

**Files:**
- Create: `.github/workflows/ci.yml` (repo's CI; adjust to the actual provider)

**Interfaces:**
- Produces: a **required-for-merge** CI job that runs, on every PR:
  `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`;
  the **Postgres-marked** suites with `POSTGRES_TEST_URL` (and
  `POSTGRES_TEST_RO_URL`) from CI secrets pointing at the Neon `penny-test`
  branch (`uv run pytest -q -m postgres`); and the Playwright E2E
  (`cd frontend && npx playwright test`) headless. Later phases append their
  suites to this same job; Phase 6 adds the durable guards.

- [ ] **Step 1:** Author `ci.yml` with those steps; mark the job a required
  status check on the branch.
- [ ] **Step 2:** Push a branch and confirm it runs green on the current tree;
  confirm a deliberately-broken RLS policy (drop a `WITH CHECK`) turns it red,
  then revert.
- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: standing regression gate (ruff + pytest + postgres suites + e2e)"
```

---

## Modularization

**Design principle (epic-wide):** wherever a unit has a genuinely clean
boundary, structure it so it *could* be lifted into a standalone package
portable to other projects — no Penny-specific coupling in the core. This is
not premature abstraction: the module still ships inside this phase, in-tree,
consumed directly. We only call out the extraction where the seam is already
clean, and we keep the *shape* portable so a later lift-and-shift is mechanical
rather than a rewrite.

**Portable module: a multi-tenant-Postgres toolkit (candidate `tenancy` package).**

The tenancy primitives introduced here form a self-contained toolkit for
adding household/owner/visibility isolation to *any* SQLAlchemy + Postgres app,
independent of Penny's domain tables.

- **What's in the core:**
  - `RequestContext` / `SessionMode` / `NIL_USER_UUID` and the `ContextVar`
    plumbing (`set_/get_/require_/reset_request_context`, `effective_user_id`) —
    Tasks 1–2. A request-scoped principal carried out-of-band from call
    signatures.
  - `session_for(ctx)` + the transaction-local session binding
    (`_apply_rls_settings` → `SET LOCAL` / `set_config('app.current_*', …, true)`)
    — Task 8. The generic "stamp the connection with the current principal so
    RLS can read it" mechanism.
  - `visible_filter(model, ctx)` — Task 9. A parametric SQLAlchemy predicate
    builder: it takes *any* model exposing `household_id` / `owner_user_id` /
    `visibility` and returns the individual-vs-joint clause. It never names a
    concrete table.
  - The RLS policy pattern itself — Task 10 / migration 011: the
    `tenant_isolation` policy shape (USING **and** WITH CHECK, the nil-user
    sentinel for the shared/joint view, `FORCE ROW LEVEL SECURITY`,
    dialect-guarded DDL) expressed against the `app.current_household` /
    `app.current_user` GUCs.

- **Seam / interface:** everything in the core reads a `RequestContext` and
  assumes only the *conventional* tenancy column triple
  (`household_id`, `owner_user_id`, `visibility`) plus the two session GUCs. It
  makes no assumption about which tables exist or what they mean — it works for
  any owner/household/visibility schema.

- **Keep OUT of the core (these are consumers, not the toolkit):** Penny's
  concrete ORM models (`Household`, `User`, `PlaidAccount`, the financial
  tables), the façade query methods (`list_visible_plaid_transactions` et al.),
  the dev-stub principal's Penny-specific header/env names
  (`X-Penny-*` / `PENNY_DEV_*`), and the taxonomy/backfill wiring. These import
  the toolkit; the toolkit never imports them.

- **Portable to:** any SQLAlchemy-on-Postgres project that needs per-request,
  RLS-enforced multi-tenancy with a private/shared visibility model.

---

## Self-Review

**Spec coverage check (spec § → task):**
- Household/User identity → Task 3. Revived `plaid_accounts` + visibility →
  Task 4. Denormalized columns → Tasks 5/7. RLS user-centric policy + joint
  sentinel → Tasks 8/10. App-level filtering → Task 9. `RequestContext` + dev
  stub → Tasks 1/2/11. Migration expand→backfill→contract → Tasks 5/6/7.
  Per-household taxonomy → Task 12. Token encryption → Task 13. Test suites
  (leakage / privacy / joint) → Tasks 10/14. Reference-data scoping (merchants
  global, categories household-only) → Tasks 5/12 (merchants untouched = global).
  Workspace partitioning → **deferred to phase 1b** (noted in Task 11 interim).
- Gap intentionally deferred: workspace hybrid (phase 1b), real auth (phase 2).

**Placeholder scan:** Task 14's battery names the five tests and their
assertions in prose with an explicit "no placeholders" instruction; every code
step elsewhere contains real code. Migrations 007/009/010/012/013 describe the
exact `op.*` calls; the implementer writes the symmetric DDL shown for 006/008/011.

**Type consistency:** `RequestContext{user_id: uuid.UUID, household_id:
uuid.UUID, session_mode: SessionMode}` used identically in Tasks 1, 2, 8, 9, 11.
`visible_filter(model, ctx)` and `effective_user_id(ctx)` names stable across
Tasks 8/9. `is_encrypted`/`encrypt_token`/`decrypt_token` stable in Task 13.
Visibility literals `'private'`/`'shared'` consistent throughout.

## Execution Handoff

After review, choose an execution approach (subagent-driven recommended; inline
with checkpoints otherwise). Phase 1a should be executed in a worktree off
`main`/`feat/account-creation`; RLS tasks need `POSTGRES_TEST_URL` pointed at the
Neon `penny-test` branch.
