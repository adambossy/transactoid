# Phase 4 — Signup / Account-Creation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 4 design](../specs/2026-07-02-phase-4-signup-ui-design.md).
> **Prev:** [Phase 2 — Auth](2026-07-01-phase-2-auth-social-login-design.md) ·
> **Next:** [Phase 5 — Onboarding](2026-06-27-phase-5-onboarding.md)

**Goal:** Open self-serve signup where each new user is auto-provisioned an
isolated solo household, plus an invite flow that lets a member bring **new**
people directly into their household — no merge, no multi-household membership.

**Architecture:** One new service (`penny/signup.py`) owns provision-or-join
logic; phase 2's auth dependency calls it in the unknown-user branch. Invites
pre-create a **pending `users` row** (`external_auth_id IS NULL`) in the
inviter's household — which phase 2's existing first-login linking then claims —
so "invite" and "link" share one mechanism. New API routes (`/api/me`,
`/api/invites`, `/api/household`) and a frontend invite screen sit on top.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, phase-1a `Household`/`User`/
`RequestContext`/`session_for`/`seed_taxonomy_for_household`, Clerk (Invitations
API), Vite + React 19 + `@clerk/clerk-react`.

## Global Constraints

- **Verification gate (run before completing every code task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Depends on:** Phases 1a and 2 merged. This plan **owns** the unknown-user
  branch that phase 2's spec marked as changing from 403 → provision; phase 2's
  auth dependency calls `resolve_or_provision_identity` (Task 2).
- **Invariant:** one individual = one household. A pending invite is a `users`
  row with `external_auth_id IS NULL`; first login claims it via phase 2's
  atomic linking `UPDATE`.
- **Emails** are stored/matched lowercased. `household_id` is **never** taken
  from a request body — invites always target `ctx.household_id`.
- Workspace prefixes are created lazily by phase 1b on first use, so signup
  provisioning does household + user + taxonomy only (no phase-1b coupling).

## File structure

- Create: `backend/penny/signup.py` — `provision_solo_household`,
  `resolve_or_provision_identity`, invite services.
- Modify: `backend/penny/api/main.py` — new routes `/api/me`, `/api/invites`
  (POST/GET), `/api/invites/{email}` (DELETE), `/api/household` (PATCH).
- Create: `backend/penny/adapters/clerk.py` — thin Clerk Invitations adapter
  (`create_invitation`, `revoke_invitation`), injectable for tests.
- Modify: `backend/penny/config.py` / `.env.example` — Clerk secret already from
  phase 2; nothing new required beyond it.
- Test: `backend/tests/test_signup.py`,
  `backend/tests/adapters/db/test_signup_isolation.py` (Postgres-marked),
  `backend/tests/api/test_invites.py`.
- Frontend: `frontend/src/InviteScreen.tsx` (new), modify
  `frontend/src/ChatScreen.tsx` / app shell to call `/api/me` and route to invites.

---

### Task 1: `provision_solo_household`

**Files:**
- Create: `backend/penny/signup.py`
- Test: `backend/tests/test_signup.py`

**Interfaces:**
- Consumes: `Household`, `User` (phase 1a); `seed_taxonomy_for_household`
  (phase 1a, `bootstrap.py`); `get_db`.
- Produces: `provision_solo_household(session, *, email: str, external_auth_id:
  str) -> tuple[uuid.UUID, uuid.UUID]` returning `(household_id, user_id)`.
  Creates a household (name = `f"{local_part}'s household"`), a user (lowercased
  email, `external_auth_id` set), and seeds the taxonomy. Idempotent: if a user
  with that email already exists, returns its `(household_id, user_id)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_signup.py
from penny.db import get_db
from penny.signup import provision_solo_household
from penny.adapters.db.models import Category, User


def test_provision_creates_household_user_and_taxonomy(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = provision_solo_household(
            s, email="Sam@Example.com", external_auth_id="clerk_abc"
        )
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.email == "sam@example.com"
        assert u.household_id == hid
        assert u.external_auth_id == "clerk_abc"
        assert s.query(Category).filter(Category.household_id == hid).count() > 0


def test_provision_is_idempotent_on_email(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        a = provision_solo_household(s, email="sam@example.com", external_auth_id="c1")
    with get_db().session() as s:
        b = provision_solo_household(s, email="sam@example.com", external_auth_id="c1")
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_signup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.signup'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/signup.py
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from penny.adapters.db.models import Household, User
from penny.bootstrap import seed_taxonomy_for_household


def provision_solo_household(
    session: Session, *, email: str, external_auth_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    normalized = email.strip().lower()
    existing = session.query(User).filter(User.email == normalized).one_or_none()
    if existing is not None:
        return existing.household_id, existing.user_id
    local = normalized.split("@", 1)[0]
    hh = Household(name=f"{local}'s household")
    session.add(hh)
    session.flush()
    user = User(household_id=hh.household_id, email=normalized,
                external_auth_id=external_auth_id)
    session.add(user)
    session.flush()
    seed_taxonomy_for_household(session, hh.household_id)
    return hh.household_id, user.user_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_signup.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/signup.py backend/tests/test_signup.py
git commit -m "feat(signup): provision_solo_household (household + user + taxonomy)"
```

---

### Task 2: `resolve_or_provision_identity` (the unknown-user branch)

**Files:**
- Modify: `backend/penny/signup.py`
- Test: `backend/tests/test_signup.py`

**Interfaces:**
- Consumes: `provision_solo_household` (Task 1); `User`; `RequestContext`,
  `SessionMode` (phase 1a).
- Produces: `resolve_or_provision_identity(session, *, email: str,
  external_auth_id: str) -> tuple[uuid.UUID, uuid.UUID]` returning
  `(household_id, user_id)`. Precedence: (1) existing user by
  `external_auth_id`; (2) a **pending** row by email (`external_auth_id IS
  NULL`) → claim it (set `external_auth_id`) and join that household; (3)
  otherwise provision a solo household. Phase 2's auth dependency calls this and
  wraps the result in a `RequestContext`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_signup.py
import uuid
from penny.adapters.db.models import Household, User
from penny.signup import resolve_or_provision_identity


def test_pending_invite_is_claimed_and_joins_that_household(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hh = Household(name="Inviter HH"); s.add(hh); s.flush()
        s.add(User(household_id=hh.household_id, email="guest@example.com",
                   external_auth_id=None))  # pending invite
        inviter_hid = hh.household_id
    with get_db().session() as s:
        hid, uid = resolve_or_provision_identity(
            s, email="guest@example.com", external_auth_id="clerk_guest"
        )
    assert hid == inviter_hid  # joined the inviter's household, no new one
    with get_db().session() as s:
        u = s.query(User).filter(User.user_id == uid).one()
        assert u.external_auth_id == "clerk_guest"


def test_no_pending_row_provisions_solo(isolated_db):
    get_db().create_schema()
    with get_db().session() as s:
        hid, uid = resolve_or_provision_identity(
            s, email="solo@example.com", external_auth_id="clerk_solo"
        )
        # brand-new solo household: the only user in it
        assert s.query(User).filter(User.household_id == hid).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_signup.py -k resolve -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_or_provision_identity'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/signup.py
def resolve_or_provision_identity(
    session: Session, *, email: str, external_auth_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    normalized = email.strip().lower()
    by_sub = session.query(User).filter(
        User.external_auth_id == external_auth_id
    ).one_or_none()
    if by_sub is not None:
        return by_sub.household_id, by_sub.user_id
    # Claim a pending invite atomically (phase-2 first-login linking).
    claimed = session.query(User).filter(
        User.email == normalized, User.external_auth_id.is_(None)
    ).one_or_none()
    if claimed is not None:
        claimed.external_auth_id = external_auth_id
        session.flush()
        return claimed.household_id, claimed.user_id
    return provision_solo_household(
        session, email=normalized, external_auth_id=external_auth_id
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_signup.py -k resolve -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/signup.py backend/tests/test_signup.py
git commit -m "feat(signup): resolve-or-provision identity (claim pending invite else provision)"
```

---

### Task 3: Invite creation + `POST /api/invites`

**Files:**
- Create: `backend/penny/adapters/clerk.py`
- Modify: `backend/penny/signup.py`, `backend/penny/api/main.py`
- Test: `backend/tests/api/test_invites.py`

**Interfaces:**
- Consumes: `require_request_context` (phase 1a/2); `User`; an injectable
  `ClerkInvites` protocol.
- Produces:
  - `penny/adapters/clerk.py`: `class ClerkInvites` with
    `create_invitation(email: str) -> None` and `revoke_invitation(email: str)
    -> None` (real impl calls Clerk; a `FakeClerkInvites` is used in tests).
  - `create_invite(session, ctx, *, email, clerk: ClerkInvites) -> str` — rejects
    (raises `InviteError`) if an **active** user (`external_auth_id` set) has that
    email; else creates a pending `users` row in `ctx.household_id` and calls
    `clerk.create_invitation`. Idempotent on a pending email.
  - `POST /api/invites` → 201 on success, **409** `InviteError` when the email is
    already an active account.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_invites.py
import uuid
import pytest
from penny.db import get_db
from penny.adapters.db.models import Household, User
from penny.tenancy.context import RequestContext, SessionMode
from penny.signup import create_invite, InviteError


class FakeClerkInvites:
    def __init__(self): self.sent = []
    def create_invitation(self, email): self.sent.append(email)
    def revoke_invitation(self, email): self.sent.remove(email)


def _ctx(hid, uid):
    return RequestContext(user_id=uid, household_id=hid, session_mode=SessionMode.INDIVIDUAL)


def test_create_invite_makes_pending_row_and_calls_clerk(isolated_db):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="HH"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u); s.flush(); hid, uid = hh.household_id, u.user_id
    clerk = FakeClerkInvites()
    with db.session_for(_ctx(hid, uid)) as s:
        create_invite(s, _ctx(hid, uid), email="Guest@X.com", clerk=clerk)
    assert clerk.sent == ["guest@x.com"]
    with db.session() as s:
        p = s.query(User).filter(User.email == "guest@x.com").one()
        assert p.household_id == hid and p.external_auth_id is None


def test_invite_rejects_active_account(isolated_db):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="HH"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        other = User(household_id=hh.household_id, email="taken@x.com", external_auth_id="c2")
        s.add_all([u, other]); s.flush(); hid, uid = hh.household_id, u.user_id
    with pytest.raises(InviteError):
        with db.session_for(_ctx(hid, uid)) as s:
            create_invite(s, _ctx(hid, uid), email="taken@x.com", clerk=FakeClerkInvites())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_invites.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_invite'`.

- [ ] **Step 3: Write minimal implementation**

Add to `signup.py`:

```python
class InviteError(Exception):
    """Raised when an email cannot be invited (already an active account)."""


def create_invite(session, ctx, *, email, clerk) -> str:
    normalized = email.strip().lower()
    existing = session.query(User).filter(User.email == normalized).one_or_none()
    if existing is not None and existing.external_auth_id is not None:
        raise InviteError(f"{normalized} already has an account")
    if existing is None:
        session.add(User(household_id=ctx.household_id, email=normalized,
                         external_auth_id=None))
        session.flush()
    clerk.create_invitation(normalized)
    return normalized
```

Create `adapters/clerk.py` with the real `ClerkInvites` (calls the Clerk
Invitations REST API using the phase-2 `CLERK_SECRET_KEY`). Wire `POST
/api/invites` in `main.py`: read `ctx` from the auth dependency, call
`create_invite`, return 201; map `InviteError` → `HTTPException(status_code=409)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_invites.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/clerk.py backend/penny/signup.py \
  backend/penny/api/main.py backend/tests/api/test_invites.py
git commit -m "feat(signup): invite new users (pending row + Clerk invitation, 409 on active email)"
```

---

### Task 4: List + revoke invites

**Files:**
- Modify: `backend/penny/signup.py`, `backend/penny/api/main.py`
- Test: `backend/tests/api/test_invites.py`

**Interfaces:**
- Produces: `list_pending_invites(session, ctx) -> list[str]` (emails with
  `external_auth_id IS NULL` in `ctx.household_id`); `revoke_invite(session, ctx,
  *, email, clerk)` (deletes the pending row + `clerk.revoke_invitation`; no-op
  if already claimed/active — never deletes an active user). Routes `GET
  /api/invites` and `DELETE /api/invites/{email}`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/api/test_invites.py
from penny.signup import list_pending_invites, revoke_invite, create_invite


def test_list_and_revoke(isolated_db):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="HH"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u); s.flush(); hid, uid = hh.household_id, u.user_id
    clerk = FakeClerkInvites()
    ctx = _ctx(hid, uid)
    with db.session_for(ctx) as s:
        create_invite(s, ctx, email="g@x.com", clerk=clerk)
    with db.session_for(ctx) as s:
        assert list_pending_invites(s, ctx) == ["g@x.com"]
    with db.session_for(ctx) as s:
        revoke_invite(s, ctx, email="g@x.com", clerk=clerk)
    with db.session_for(ctx) as s:
        assert list_pending_invites(s, ctx) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_invites.py -k list_and_revoke -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/signup.py
def list_pending_invites(session, ctx) -> list[str]:
    rows = session.query(User).filter(
        User.household_id == ctx.household_id, User.external_auth_id.is_(None)
    ).all()
    return [r.email for r in rows]


def revoke_invite(session, ctx, *, email, clerk) -> None:
    normalized = email.strip().lower()
    row = session.query(User).filter(
        User.household_id == ctx.household_id,
        User.email == normalized,
        User.external_auth_id.is_(None),
    ).one_or_none()
    if row is None:
        return
    session.delete(row)
    session.flush()
    clerk.revoke_invitation(normalized)
```

Wire `GET /api/invites` and `DELETE /api/invites/{email}` in `main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_invites.py -k list_and_revoke -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/signup.py backend/penny/api/main.py backend/tests/api/test_invites.py
git commit -m "feat(signup): list + revoke pending invites"
```

---

### Task 5: `GET /api/me` bootstrap + `PATCH /api/household`

**Files:**
- Modify: `backend/penny/api/main.py`, `backend/penny/signup.py`
- Test: `backend/tests/api/test_me.py`

**Interfaces:**
- Produces: `GET /api/me` → `{user_id, email, household_id, household_name}`.
  Because the auth dependency already ran `resolve_or_provision_identity`, the
  household exists by the time `/api/me` runs (first call after signup triggers
  provisioning inside the dependency). `PATCH /api/household` `{name}` renames the
  caller's household (`rename_household(session, ctx, *, name)`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_me.py
from penny.db import get_db
from penny.adapters.db.models import Household, User
from penny.tenancy.context import RequestContext, SessionMode
from penny.signup import rename_household


def test_rename_household(isolated_db):
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="old"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="me@x.com", external_auth_id="c1")
        s.add(u); s.flush(); hid, uid = hh.household_id, u.user_id
    ctx = RequestContext(user_id=uid, household_id=hid, session_mode=SessionMode.INDIVIDUAL)
    with db.session_for(ctx) as s:
        rename_household(s, ctx, name="Bossy Household")
    with db.session() as s:
        assert s.query(Household).filter(Household.household_id == hid).one().name == "Bossy Household"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_me.py -v`
Expected: FAIL — `ImportError: cannot import name 'rename_household'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/signup.py
from penny.adapters.db.models import Household


def rename_household(session, ctx, *, name: str) -> None:
    hh = session.query(Household).filter(
        Household.household_id == ctx.household_id
    ).one()
    hh.name = name
    session.flush()
```

Wire `GET /api/me` (reads `ctx`, loads user + household, returns the dict) and
`PATCH /api/household` (calls `rename_household`) in `main.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_me.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/signup.py backend/penny/api/main.py backend/tests/api/test_me.py
git commit -m "feat(api): /api/me bootstrap + PATCH /api/household rename"
```

---

### Task 6: Frontend — invite screen + `/api/me` wiring

**Files:**
- Create: `frontend/src/InviteScreen.tsx`
- Modify: `frontend/src/ChatScreen.tsx` (or app shell) — call `/api/me` after
  auth; add nav to the invite screen; show the household name.
- Test: manual (frontend has no test harness in this repo today).

**Interfaces:**
- Consumes: phase-2 Clerk `getToken()` + authed transport; `/api/me`,
  `/api/invites` routes (Tasks 3–5).
- Produces: an invite UI (enter email → `POST /api/invites`; list pending with
  revoke; render the **409** "already has an account — they must sign up fresh"
  message) and a post-auth bootstrap that fetches `/api/me`.

- [ ] **Step 1: Implement the invite screen**

Create `InviteScreen.tsx`: a form posting `{email}` to `/api/invites` with the
Clerk bearer token, a pending-invites list from `GET /api/invites` with a revoke
button (`DELETE /api/invites/{email}`), and a `409` handler that shows: *"That
email already has a Penny account. To join this household they'll need to sign up
with a new account."*

- [ ] **Step 2: Wire `/api/me` on load**

In the authenticated app shell, after Clerk reports signed-in, `fetch('/api/me')`
with the bearer token; store `{household_name}` and show it in the header; expose
a link/button to the invite screen.

- [ ] **Step 3: Manual verification**

Run frontend (`npm run dev`) + backend locally with Clerk dev keys. Sign up a
brand-new Google account → confirm a solo household is created (`/api/me` returns
a fresh household). From it, invite a new email → confirm a pending invite
appears; complete signup as that email → confirm they land in the same household.
Invite an already-registered email → confirm the 409 message.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/InviteScreen.tsx frontend/src/ChatScreen.tsx
git commit -m "feat(frontend): invite screen + /api/me bootstrap"
```

---

### Task 7: Signup isolation suite (Postgres-marked)

**Files:**
- Create: `backend/tests/adapters/db/test_signup_isolation.py`

**Interfaces:**
- Consumes: `resolve_or_provision_identity`, `session_for`, RLS (phase 1a).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/adapters/db/test_signup_isolation.py
import datetime, pytest
pytestmark = pytest.mark.postgres

from penny.signup import resolve_or_provision_identity
from penny.tenancy.context import RequestContext, SessionMode
from penny.adapters.db.models import PlaidItem, PlaidTransaction

# Two independent self-serve signups get two isolated households; a run_sql-style
# SELECT from one context returns zero rows belonging to the other.
```

Implement: provision two users (`a@x.com`, `b@x.com`) via
`resolve_or_provision_identity` on `pg_db`; under each user's `RequestContext`,
seed one `PlaidItem`/`PlaidTransaction`; assert a raw
`SELECT count(*) FROM plaid_transactions` from A's context excludes B's rows and
vice versa.

- [ ] **Step 2–4: Run, implement, verify**

Run: `cd backend && POSTGRES_TEST_URL=<neon-test-url> uv run pytest tests/adapters/db/test_signup_isolation.py -v`.
Iterate until green; confirm it skips without the env var and `uv run pytest -q` is green.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/adapters/db/test_signup_isolation.py
git commit -m "test(signup): two self-serve signups are fully isolated (postgres)"
```

---

## Browser E2E Validation (Playwright)

Automated headless Playwright specs living in `frontend/e2e/<name>.spec.ts`. They
reuse the shared E2E harness introduced in **phase 1a** (test server + fixtures)
and its `signInAsTestUser` helper from **phase 2**. Clerk auth in the browser is
driven with **Clerk testing tokens** (`@clerk/testing`) so signup/sign-in runs
without a human solving bot checks. These specs validate the real signed-in
browser flows the manual checks in Task 6 describe.

---

### Task 8: E2E — self-serve signup lands in a solo household

**Files:**
- Create: `frontend/e2e/signup.spec.ts`

**Interfaces:**
- Consumes: the phase-1a Playwright harness (test server + DB reset fixtures);
  Clerk testing tokens; `/api/me`.
- Produces: a headless spec proving a brand-new Clerk test user who signs up is
  auto-provisioned a solo household whose name renders in the header.

- [ ] **Step 1: Write the failing spec**

Create `frontend/e2e/signup.spec.ts`. Using a fresh browser context, inject the
Clerk testing token, then drive the `<SignUp>` form for a **brand-new** test
email (e.g. `signup+<timestamp>@example.com`) through Clerk's test verification
code. Assert the app redirects into the authenticated shell, that `GET /api/me`
resolves a household (spy on the response or assert on rendered state), and that
the header shows the household name derived from that email's local part
(`<local-part>'s household`). Key selectors: the Clerk sign-up email/submit
fields, and a `data-testid="household-name"` header element.

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/signup.spec.ts`
Expected: FAIL — spec/selectors not yet present (or the household-name element is
missing until Task 6 wiring is in place).

- [ ] **Step 3: Make it pass**

Ensure Task 6's `/api/me` wiring exposes the header `data-testid="household-name"`
and post-signup redirect. Iterate until the spec is green headless.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/signup.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/signup.spec.ts
git commit -m "test(e2e): signup lands in a solo household with header name (playwright)"
```

---

### Task 9: E2E — invite a new email; second context joins the same household

**Files:**
- Create: `frontend/e2e/invite.spec.ts`

**Interfaces:**
- Consumes: the phase-1a harness; `signInAsTestUser` (phase 2); Clerk testing
  tokens; `/api/invites`, `/api/me`.
- Produces: a headless spec proving an invited **new** email signs up into the
  **inviter's** household (not a new one), and that inviting an **already-active**
  email surfaces the `409` "start fresh" message.

- [ ] **Step 1: Write the failing spec**

Create `frontend/e2e/invite.spec.ts` with two assertions:

1. **Invite → join same household.** In context A, `signInAsTestUser` as an
   existing member, open the Invite screen, type a brand-new email into the invite
   field, submit, and assert the email appears in the pending-invites list
   (`data-testid="pending-invite"`). Capture the inviter's household name from the
   header. In a **second browser context** (B), inject a Clerk testing token and
   complete `<SignUp>` as that same invited email; assert B's header shows the
   **same** household name as A (joined, not auto-provisioned a new solo
   household).
2. **Invite an already-registered email → 409.** Back in context A, invite an
   email that already has an active account and assert the UI renders the
   start-fresh message (`data-testid="invite-error"` containing the "sign up with
   a new account" copy) rather than adding a pending row.

Key selectors: invite email input + submit button, `pending-invite` list items,
`invite-error` banner, and the `household-name` header element (reused from
Task 8).

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/invite.spec.ts`
Expected: FAIL — invite selectors / error copy not yet wired.

- [ ] **Step 3: Make it pass**

Ensure Task 6's Invite screen exposes the `pending-invite` and `invite-error`
testids and the `409` copy. Iterate until green headless across both contexts.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/invite.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/invite.spec.ts
git commit -m "test(e2e): invited email joins inviter household; active email shows 409 (playwright)"
```

---

## Self-Review

**Spec coverage:** auto-provision → Tasks 1/2/7; invite (new users only) →
Tasks 3/4; phase-2 unknown-branch change → Task 2 (called by phase 2's
dependency); `/api/me` + household rename → Task 5; frontend signup/invite →
Task 6; open-signup isolation → Task 7. Re-link (independent Plaid items per
household) needs no code — it falls out of per-household `plaid_items` — and is
asserted implicitly by isolation (Task 7). Abuse-surface mitigation is a
spec-flagged phase-6 audit item, intentionally not built here.

**Placeholder scan:** Tasks 7 and 6-step-3 describe test/verification bodies in
prose (Postgres seed mirrors Task-2 patterns; frontend has no test harness) —
intentional; all backend service code is complete. No TBD/TODO.

**Type consistency:** `provision_solo_household(...) -> (household_id, user_id)`,
`resolve_or_provision_identity(...) -> (household_id, user_id)`, `create_invite`,
`list_pending_invites`, `revoke_invite`, `rename_household`, and `InviteError`
are used consistently across tasks; `RequestContext`/`session_for`/`SessionMode`
match phase 1a.

## Execution Handoff

After review, choose execution (subagent-driven recommended for Tasks 1–5, 7;
Task 6 is a frontend task verified manually with Clerk dev keys). The Postgres
task (7) needs `POSTGRES_TEST_URL` on the Neon `penny-test` branch. This plan
should be executed **after** the Phase 2 plan, since its Task 2 is called by
phase 2's auth dependency.
