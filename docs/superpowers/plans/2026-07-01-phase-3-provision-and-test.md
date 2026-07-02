# Phase 3 — Provision + Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 3 design](../specs/2026-07-01-phase-3-provision-and-test-design.md).
> **Prev:** [Phase 2 — Auth](2026-07-01-phase-2-auth-social-login-design.md)

**Goal:** Provision the real household + two users via an idempotent admin CLI,
link real banks locally, set per-account visibility, and validate the full
multi-tenant + auth stack against real data — rehearsed on the Neon `penny-test`
branch, then executed on prod.

**Architecture:** One code deliverable — a `penny admin` Typer command group that
reuses phase 1a's `backfill_household` helper, façade, and `RequestContext` —
plus a provisioning runbook and a real-data acceptance checklist. No new
isolation mechanism; phase 3 only exercises what phases 1a/1b/2 built.

**Tech Stack:** Python 3.12, Typer (existing `cli.py`), SQLAlchemy 2.0, the
phase-1a façade + `RequestContext`/`session_for`, Neon Postgres, Clerk (dev
instance locally), Plaid Link (localhost flow).

## Global Constraints

- **Verification gate (run before completing every code task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Prereqs:** Phases 1a, 1b, and 2 are merged. `households`/`users` are the
  identity registry and are **not** RLS-scoped; `plaid_accounts` **is**
  RLS-scoped, so visibility edits run under an explicit `RequestContext`.
- **Idempotency:** every admin command is safe to re-run; existing rows are
  returned, not duplicated. Emails are stored/matched **lowercased**.
- **Never point a dev server at prod** while rehearsing; rehearse on `penny-test`
  (`backend/.env.test`), then execute on prod deliberately.
- **Admin CLI is never exposed over HTTP** — it is a local maintenance tool only.

## File structure

- Create: `backend/penny/admin.py` — the `admin` Typer sub-app (commands +
  their service calls). Kept separate from `cli.py`'s user-facing `run`
  commands so the maintenance surface is isolated.
- Modify: `backend/penny/cli.py` — register the `admin` sub-app
  (`app.add_typer(admin_app, name="admin")`).
- Modify: `backend/penny/adapters/db/facade.py` — add the small read/write
  helpers the admin commands need (list accounts, set visibility) if not already
  present from phase 1a.
- Test: `backend/tests/test_admin_cli.py` (SQLite for CRUD idempotency),
  `backend/tests/adapters/db/test_set_visibility.py` (Postgres-marked for the
  RLS-context path).
- Runbook (docs, no code): the provisioning + acceptance sections at the end of
  this plan are executed by a human/operator, not an agent.

---

### Task 1: `penny admin create-household`

**Files:**
- Create: `backend/penny/admin.py`
- Modify: `backend/penny/cli.py` (register sub-app)
- Test: `backend/tests/test_admin_cli.py`

**Interfaces:**
- Consumes: phase-1a `DB`/`get_db`, `Household` model.
- Produces: `create_household(name: str) -> uuid.UUID` (service fn in
  `admin.py`); Typer command `penny admin create-household --name <str>` that
  prints the household id. Idempotent on `name` (returns the existing id if a
  household with that exact name exists).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_cli.py
from penny.admin import create_household
from penny.db import get_db


def test_create_household_is_idempotent(isolated_db):
    get_db().create_schema()
    a = create_household(name="Bossy")
    b = create_household(name="Bossy")
    assert a == b  # same id on re-run, no duplicate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_create_household_is_idempotent -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.admin'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/admin.py
from __future__ import annotations

import uuid

import typer

from penny.adapters.db.models import Household
from penny.db import get_db

admin_app = typer.Typer(help="Maintenance/admin commands (local only).")


def create_household(name: str) -> uuid.UUID:
    db = get_db()
    with db.session() as s:
        existing = s.query(Household).filter(Household.name == name).one_or_none()
        if existing is not None:
            return existing.household_id
        hh = Household(name=name)
        s.add(hh)
        s.flush()
        return hh.household_id


@admin_app.command("create-household")
def create_household_cmd(name: str = typer.Option(..., "--name")) -> None:
    hid = create_household(name=name)
    typer.echo(str(hid))
```

Register in `cli.py` (near the existing Typer `app`): `from penny.admin import
admin_app` and `app.add_typer(admin_app, name="admin")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_create_household_is_idempotent -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/admin.py backend/penny/cli.py backend/tests/test_admin_cli.py
git commit -m "feat(admin): idempotent create-household command"
```

---

### Task 2: `penny admin create-user`

**Files:**
- Modify: `backend/penny/admin.py`
- Test: `backend/tests/test_admin_cli.py`

**Interfaces:**
- Consumes: `Household`, `User` models; `create_household` (Task 1).
- Produces: `create_user(household_id: uuid.UUID, email: str) -> uuid.UUID`
  (lowercases email; idempotent on email; `external_auth_id` left null for
  phase-2 first-login linking). Command `penny admin create-user --household
  <uuid> --email <str>`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_admin_cli.py
import pytest

from penny.admin import create_household, create_user
from penny.db import get_db


def test_create_user_idempotent_and_lowercased(isolated_db):
    get_db().create_schema()
    hid = create_household(name="Bossy")
    u1 = create_user(household_id=hid, email="Adam@Spara.Co")
    u2 = create_user(household_id=hid, email="adam@spara.co")
    assert u1 == u2  # case-insensitive, no duplicate

    from penny.adapters.db.models import User
    with get_db().session() as s:
        row = s.query(User).filter(User.user_id == u1).one()
        assert row.email == "adam@spara.co"
        assert row.external_auth_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_create_user_idempotent_and_lowercased -v`
Expected: FAIL — `ImportError: cannot import name 'create_user'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/admin.py
from penny.adapters.db.models import User


def create_user(household_id: uuid.UUID, email: str) -> uuid.UUID:
    normalized = email.strip().lower()
    db = get_db()
    with db.session() as s:
        existing = s.query(User).filter(User.email == normalized).one_or_none()
        if existing is not None:
            return existing.user_id
        user = User(household_id=household_id, email=normalized)
        s.add(user)
        s.flush()
        return user.user_id


@admin_app.command("create-user")
def create_user_cmd(
    household: uuid.UUID = typer.Option(..., "--household"),
    email: str = typer.Option(..., "--email"),
) -> None:
    uid = create_user(household_id=household, email=email)
    typer.echo(str(uid))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_create_user_idempotent_and_lowercased -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/admin.py backend/tests/test_admin_cli.py
git commit -m "feat(admin): idempotent create-user command (lowercased email)"
```

---

### Task 3: `penny admin list-accounts`

**Files:**
- Modify: `backend/penny/admin.py`
- Test: `backend/tests/test_admin_cli.py`

**Interfaces:**
- Consumes: `PlaidAccount` model; phase-1a `RequestContext`, `DB.session_for`.
- Produces: `list_accounts(household_id, admin_user_id) -> list[tuple[str, str,
  str]]` returning `(account_id, owner_email, visibility)`; command
  `penny admin list-accounts --household <uuid>` printing a table. Runs under an
  admin `RequestContext` for that household (so RLS is satisfied).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_admin_cli.py
from penny.admin import create_household, create_user, list_accounts
from penny.adapters.db.models import PlaidAccount, PlaidItem
from penny.db import get_db


def test_list_accounts_returns_owner_and_visibility(isolated_db):
    db = get_db(); db.create_schema()
    hid = create_household(name="Bossy")
    uid = create_user(household_id=hid, email="a@x.com")
    with db.session() as s:
        s.add(PlaidItem(item_id="i1", access_token="t", household_id=hid, owner_user_id=uid))
        s.flush()
        s.add(PlaidAccount(account_id="acct-1", item_id="i1", owner_user_id=uid,
                           household_id=hid, visibility="private"))
    rows = list_accounts(household_id=hid, admin_user_id=uid)
    assert ("acct-1", "a@x.com", "private") in rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_list_accounts_returns_owner_and_visibility -v`
Expected: FAIL — `ImportError: cannot import name 'list_accounts'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/admin.py
from penny.adapters.db.models import PlaidAccount
from penny.tenancy.context import RequestContext, SessionMode


def list_accounts(household_id: uuid.UUID, admin_user_id: uuid.UUID):
    ctx = RequestContext(user_id=admin_user_id, household_id=household_id,
                         session_mode=SessionMode.INDIVIDUAL)
    db = get_db()
    with db.session_for(ctx) as s:
        rows = (
            s.query(PlaidAccount, User.email)
            .join(User, PlaidAccount.owner_user_id == User.user_id)
            .filter(PlaidAccount.household_id == household_id)
            .all()
        )
        out = [(a.account_id, email, a.visibility) for a, email in rows]
    return out


@admin_app.command("list-accounts")
def list_accounts_cmd(
    household: uuid.UUID = typer.Option(..., "--household"),
    admin_user: uuid.UUID = typer.Option(..., "--admin-user"),
) -> None:
    for account_id, email, visibility in list_accounts(household_id=household, admin_user_id=admin_user):
        typer.echo(f"{account_id}\t{email}\t{visibility}")
```

> Note: `--admin-user` sets the RLS context. Because visibility edits (Task 4)
> and listing operate on RLS-scoped `plaid_accounts`, the admin acts *as* a user
> in the household. To see accounts owned by another member, list under that
> member's id, or run both members. (An admin who must see everything at once
> would need a BYPASSRLS maintenance role — out of scope; not needed for two
> users.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_admin_cli.py::test_list_accounts_returns_owner_and_visibility -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/admin.py backend/tests/test_admin_cli.py
git commit -m "feat(admin): list-accounts with owner + visibility"
```

---

### Task 4: `penny admin set-account-visibility`

**Files:**
- Modify: `backend/penny/admin.py`
- Modify: `backend/penny/adapters/db/facade.py` (a `set_account_visibility`
  helper that updates `plaid_accounts` + the denormalized copies in one txn)
- Test: `backend/tests/adapters/db/test_set_visibility.py` (Postgres-marked)

**Interfaces:**
- Consumes: `PlaidAccount`; the denormalized `visibility` columns on transaction
  tables (phase 1a); `session_for`.
- Produces: `DB.set_account_visibility(session, *, account_id: str, visibility:
  str)` updating `plaid_accounts.visibility` **and** the denormalized
  `visibility` on that account's `plaid_transactions`/`derived_transactions`
  rows; `set_account_visibility(account_id, visibility, owner_user_id,
  household_id)` service fn; command `penny admin set-account-visibility
  --account <id> --visibility private|shared --owner <uuid> --household <uuid>`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_set_visibility.py
import pytest

pytestmark = pytest.mark.postgres

from penny.admin import create_household, create_user, set_account_visibility, list_accounts
# seeds an account private, flips to shared, asserts plaid_accounts + a
# derived_transactions row both reflect 'shared' under the owner's RLS context.
```

(Implement the full seed/flip/assert mirroring Task 3's seed plus a
`derived_transactions` row; assert both the `plaid_accounts` row and the
denormalized transaction row read `shared` after the flip.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_set_visibility.py -v`
Expected: FAIL — `ImportError` / visibility not propagated to denormalized rows.

- [ ] **Step 3: Write minimal implementation**

Add `DB.set_account_visibility` to `facade.py`:

```python
def set_account_visibility(self, session, *, account_id: str, visibility: str) -> None:
    if visibility not in ("private", "shared"):
        raise ValueError(f"invalid visibility: {visibility}")
    acct = session.query(PlaidAccount).filter(
        PlaidAccount.account_id == account_id
    ).one()
    acct.visibility = visibility
    for model in (PlaidTransaction, DerivedTransaction):
        session.query(model).filter(model.account_id == account_id).update(
            {"visibility": visibility}, synchronize_session=False
        )
```

Add the service fn + command to `admin.py` that wraps it in `session_for(owner
ctx)`. (`--owner`/`--household` build the `RequestContext` so RLS permits the
update.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_set_visibility.py -v`
Expected: PASS. (Skips without the env var.)

- [ ] **Step 5: Commit**

```bash
git add backend/penny/admin.py backend/penny/adapters/db/facade.py \
  backend/tests/adapters/db/test_set_visibility.py
git commit -m "feat(admin): set-account-visibility flips account + denormalized rows"
```

---

### Task 5 (Runbook, not code): Provisioning — rehearse on `penny-test`, then prod

Execute manually; check each box. **Rehearse the entire list against `penny-test`
first, then repeat against prod.**

- [ ] Start the backend locally against the target DB
  (`set -a && source .env.test && set +a` for test; the prod env for prod) with
  `PENNY_AUTH_MODE=clerk` and Clerk dev keys.
- [ ] `uv run penny admin create-household --name "<your household>"` → note the
  household id `H`.
- [ ] `uv run penny admin create-user --household H --email you@example.com` → `U1`.
- [ ] `uv run penny admin create-user --household H --email wife@example.com` → `U2`.
- [ ] In the Clerk dashboard, add both emails to the allowlist.
- [ ] Each spouse signs in locally via Clerk once → confirm `users.external_auth_id`
  is populated (phase-2 first-login linking) for both.
- [ ] Confirm the phase-1a backfill assigned your existing data to `H` / `U1` /
  `visibility='private'` (spot-check `list-accounts --household H --admin-user U1`).
- [ ] Each spouse links their own banks via the local Plaid Link flow.
- [ ] `uv run penny admin list-accounts --household H --admin-user U1` (and `U2`)
  to review owners + visibility.
- [ ] `uv run penny admin set-account-visibility --account <id> --visibility shared
  --owner <U> --household H` for each account you intend to share; re-list to confirm.

---

### Task 6 (Runbook, not code): Real-data acceptance checklist

Record the outcome as a completion artifact (paste `run_sql` probe results).

- [ ] **Automated suites green** against `penny-test` (prod-equivalent config):
  `POSTGRES_TEST_URL=<test> uv run pytest -q -m postgres` — phase 1a/1b/2
  cross-household leakage, within-household privacy, joint, workspace, and auth
  suites all pass.
- [ ] **Within-household privacy (real data):** logged in as `U1` (individual),
  confirm the UI and a `run_sql` `SELECT count(*) FROM derived_transactions`
  exclude `U2`'s private accounts; repeat as `U2`.
- [ ] **Joint session (real data):** a joint conversation returns shared-only —
  neither spouse's private transactions/memories/reports appear.
- [ ] **Conversation isolation:** `U1` cannot open `U2`'s individual conversation
  (403/404); a joint thread is visible to both.
- [ ] **Cron:** run the per-user reports and the household shared report; confirm
  each per-user report is correctly scoped and reaches only that user, and the
  shared report is shared-only and reaches both.
- [ ] **Workspace (phase 1b):** a real agent run materializes, writes back, and
  versions; a joint run never resolves a private prefix.
- [ ] **Secrets:** `SELECT access_token FROM plaid_items LIMIT 1` returns
  ciphertext; grep logs confirm no plaintext token.
- [ ] Only after all boxes pass on `penny-test`, repeat provisioning (Task 5) +
  this checklist against **prod**.

---

## Self-Review

**Spec coverage:** admin CLI (create-household/create-user/list-accounts/
set-account-visibility) → Tasks 1–4. Provisioning runbook (rehearse→prod, Clerk
allowlist, first-login linking, bank linking, visibility flips) → Task 5.
Acceptance checklist (automated suites + within-household/joint/conversation/
cron/workspace/secrets on real data) → Task 6. Environment (local + test→prod)
and leakage-validation (synthetic cross-household via phase-1a suite + real
within-household) → Tasks 5/6. No spec requirement is unaddressed.

**Placeholder scan:** Task 4's Postgres test says "implement the full seed/flip/
assert" in prose rather than full code — intentional, since it mirrors Task 3's
seed exactly (repeated there); every other code step is complete. Runbook Tasks
5/6 are checklists by design (operator-executed), not code.

**Type consistency:** `create_household(name)->uuid`, `create_user(household_id,
email)->uuid`, `list_accounts(household_id, admin_user_id)`,
`set_account_visibility(...)`, and `RequestContext`/`session_for`/`SessionMode`
are used consistently across tasks and match phase 1a's interfaces.

## Execution Handoff

After review, choose execution (subagent-driven recommended for Tasks 1–4;
Tasks 5–6 are operator runbooks you execute against `penny-test` then prod). The
Postgres task (4) needs `POSTGRES_TEST_URL` on the Neon `penny-test` branch.
