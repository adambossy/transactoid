# Phase 2 — Auth / Social Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 2 design](../specs/2026-07-01-phase-2-auth-social-login-design.md).
> **Real Clerk wiring (app id, keys, Vite/React SDK, CLI runbook):** see the
> [Clerk wiring addendum](../specs/2026-07-04-phase-2-clerk-wiring-addendum.md) —
> the backend is built against a mock JWKS; swapping in the real Clerk instance +
> frontend SDK is a post-merge follow-up.
> **Prev:** [Phase 1a plan](2026-06-27-phase-1a-multi-tenant-data-model.md) ·
> **Next:** [Phase 3 plan](2026-07-01-phase-3-provision-and-test.md), [Phase 4 plan](2026-07-02-phase-4-signup-ui.md)

**Goal:** Replace the phase-1a dev-stub principal with verified Clerk identity
(Google login) — JWT verification, email-linked users, per-conversation session
mode, conversation scoping, CORS lockdown, read-only `run_sql`, no-recipient
email tool, and an explicit cron principal.

**Architecture:** A `penny/auth/` package owns settings (fail-closed), JWT
verification (JWKS from config), and identity linking. A FastAPI generator
dependency turns a bearer token into the phase-1a `RequestContext`, sets the
ContextVar, and resets it after the response. The conversation store gains
tenant columns and filters every access; `/api/chat` derives the turn's
`session_mode` from the conversation row. The data layer is untouched — RLS
does the enforcement once the context is set.

**Tech Stack:** Python 3.12, FastAPI, `pyjwt[crypto]` (RS256 + JWKS), SQLAlchemy
2.0, phase-1a `penny.tenancy` (`RequestContext`, `SessionMode`,
`set_request_context`/`reset_request_context`, `NIL_USER_UUID`), Clerk
(`@clerk/clerk-react` on the frontend), Vite + React 19.

## Global Constraints

- **Verification gate (run before completing every task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Fail closed.** `PENNY_AUTH_MODE` defaults to `clerk`. Startup raises if the
  mode is invalid, or if clerk mode is missing `PENNY_CLERK_ISSUER`,
  `PENNY_CLERK_JWKS_URL`, or `PENNY_FRONTEND_ORIGIN`. In clerk mode the dev-stub
  path is unreachable — no `X-Penny-*` header fallback.
- **Identity comes only from the verified token.** `user_id`/`owner_user_id`
  are never read from a request body. `session_mode` values are only
  `individual` | `joint`.
- **JWKS URL comes from config, never from the token's `iss`.** Verify `iss`
  against `PENNY_CLERK_ISSUER`, `exp` with 60s leeway, audience if
  `PENNY_CLERK_AUDIENCE` is set, `algorithms=["RS256"]` only.
- **Emails lowercased** on storage and lookup; require `email_verified is True`
  before linking.
- **Postgres-marked tests** (`@pytest.mark.postgres`) run only when
  `POSTGRES_TEST_URL` is set (phase-1a fixture `pg_db`).
- New env vars (`PENNY_*` prefix, keep `.env.example` current):
  `PENNY_AUTH_MODE`, `PENNY_CLERK_ISSUER`, `PENNY_CLERK_JWKS_URL`,
  `PENNY_CLERK_AUDIENCE` (optional), `PENNY_FRONTEND_ORIGIN`,
  `PENNY_AGENT_READONLY_DATABASE_URL`, `PENNY_CRON_HOUSEHOLD_ID`,
  `PENNY_CRON_USER_IDS`. Frontend: `VITE_CLERK_PUBLISHABLE_KEY`,
  `CLERK_SECRET_KEY` (backend, for phase-4 invites; documented now).

## File structure

- Create: `backend/penny/auth/__init__.py`
- Create: `backend/penny/auth/settings.py` — `AuthSettings`, `load_auth_settings()` (fail-closed).
- Create: `backend/penny/auth/jwt_verifier.py` — `ClerkJwtVerifier.verify(token) -> dict`.
- Create: `backend/penny/auth/identity.py` — `link_or_resolve_user(...)`, `AuthError`/`UnknownUserError`.
- Create: `backend/penny/api/auth.py` — the FastAPI dependency (`request_context`).
- Modify: `backend/penny/api/main.py` — CORS lockdown; dependency on `/api/chat` + `/api/sessions/{id}`; startup validation.
- Modify: `backend/penny/api/persistence/models.py` + `store.py` — tenant columns + scoped methods.
- Modify: `backend/penny/tools/analytics.py` (`run_sql`) — read-only engine.
- Modify: `backend/penny/tools/delivery.py` (`send_email_report`) — drop `to` param, derive recipients.
- Modify: `backend/penny/cli.py` — explicit cron `RequestContext`, per-user + household report jobs.
- Modify: `frontend/src/main.tsx`, `frontend/src/ChatScreen.tsx`; create `frontend/src/AuthGate.tsx`.
- Tests: `backend/tests/auth/test_settings.py`, `test_jwt_verifier.py`,
  `test_identity.py`, `backend/tests/api/test_auth_dependency.py`,
  `test_conversation_scoping.py`, `backend/tests/tools/test_run_sql_readonly.py`
  (Postgres-marked), `test_delivery_recipients.py`, `backend/tests/test_cron_context.py`.

---

### Task 1: Auth settings — fail-closed

**Files:**
- Create: `backend/penny/auth/__init__.py`, `backend/penny/auth/settings.py`
- Test: `backend/tests/auth/test_settings.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) AuthSettings(mode: str, issuer: str | None,
  jwks_url: str | None, audience: str | None, frontend_origin: str | None)`;
  `load_auth_settings() -> AuthSettings` — reads env, defaults `mode="clerk"`,
  raises `RuntimeError` on invalid mode or missing clerk-mode config. Later
  tasks call `load_auth_settings()` at startup and in the dependency.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/auth/test_settings.py
import pytest

from penny.auth.settings import load_auth_settings

CLERK_ENV = {
    "PENNY_CLERK_ISSUER": "https://x.clerk.accounts.dev",
    "PENNY_CLERK_JWKS_URL": "https://x.clerk.accounts.dev/.well-known/jwks.json",
    "PENNY_FRONTEND_ORIGIN": "https://penny.example.com",
}


def _clear(monkeypatch):
    for k in ["PENNY_AUTH_MODE", *CLERK_ENV, "PENNY_CLERK_AUDIENCE"]:
        monkeypatch.delenv(k, raising=False)


def test_defaults_to_clerk_and_fails_without_config(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(RuntimeError):
        load_auth_settings()  # clerk mode, missing issuer/jwks/origin


def test_clerk_mode_loads_with_full_config(monkeypatch):
    _clear(monkeypatch)
    for k, v in CLERK_ENV.items():
        monkeypatch.setenv(k, v)
    s = load_auth_settings()
    assert s.mode == "clerk"
    assert s.issuer == CLERK_ENV["PENNY_CLERK_ISSUER"]


def test_invalid_mode_rejected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("PENNY_AUTH_MODE", "off")
    with pytest.raises(RuntimeError):
        load_auth_settings()


def test_dev_mode_allowed_without_clerk_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("PENNY_AUTH_MODE", "dev")
    assert load_auth_settings().mode == "dev"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/auth/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.auth'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/auth/__init__.py
```

```python
# backend/penny/auth/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthSettings:
    mode: str  # "clerk" | "dev"
    issuer: str | None
    jwks_url: str | None
    audience: str | None
    frontend_origin: str | None


def load_auth_settings() -> AuthSettings:
    mode = os.environ.get("PENNY_AUTH_MODE", "").strip() or "clerk"
    if mode not in ("clerk", "dev"):
        raise RuntimeError(f"PENNY_AUTH_MODE must be 'clerk' or 'dev', got {mode!r}")
    issuer = os.environ.get("PENNY_CLERK_ISSUER", "").strip() or None
    jwks_url = os.environ.get("PENNY_CLERK_JWKS_URL", "").strip() or None
    audience = os.environ.get("PENNY_CLERK_AUDIENCE", "").strip() or None
    origin = os.environ.get("PENNY_FRONTEND_ORIGIN", "").strip() or None
    if mode == "clerk":
        missing = [
            name
            for name, val in [
                ("PENNY_CLERK_ISSUER", issuer),
                ("PENNY_CLERK_JWKS_URL", jwks_url),
                ("PENNY_FRONTEND_ORIGIN", origin),
            ]
            if val is None
        ]
        if missing:
            raise RuntimeError(f"clerk auth mode requires: {', '.join(missing)}")
    return AuthSettings(mode=mode, issuer=issuer, jwks_url=jwks_url,
                        audience=audience, frontend_origin=origin)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/auth/test_settings.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/auth backend/tests/auth/test_settings.py
git commit -m "feat(auth): fail-closed auth settings (default clerk)"
```

---

### Task 2: JWT verifier (JWKS from config)

**Files:**
- Create: `backend/penny/auth/jwt_verifier.py`
- Modify: `backend/pyproject.toml` (add `pyjwt[crypto]`)
- Test: `backend/tests/auth/test_jwt_verifier.py`

**Interfaces:**
- Consumes: `AuthSettings` (Task 1).
- Produces: `class ClerkJwtVerifier(settings: AuthSettings, *, signing_key_for:
  Callable[[str], Any] | None = None)` with `verify(token: str) -> dict`
  (claims). Raises `TokenError` (subclass of `AuthError`, defined here and
  re-exported by Task 3) on any invalid token. `signing_key_for` is injectable
  for tests; the default uses `jwt.PyJWKClient(settings.jwks_url)` — never the
  token's `iss`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/auth/test_jwt_verifier.py
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from penny.auth.jwt_verifier import ClerkJwtVerifier, TokenError
from penny.auth.settings import AuthSettings

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SETTINGS = AuthSettings(mode="clerk", issuer="https://iss.example",
                        jwks_url="https://iss.example/jwks", audience=None,
                        frontend_origin="https://app.example")


def _make(claims: dict, key=KEY, alg="RS256") -> str:
    base = {"iss": "https://iss.example", "exp": int(time.time()) + 300,
            "sub": "user_1", "email": "a@x.com", "email_verified": True}
    return jwt.encode({**base, **claims}, key, algorithm=alg)


def _verifier() -> ClerkJwtVerifier:
    return ClerkJwtVerifier(SETTINGS, signing_key_for=lambda tok: KEY.public_key())


def test_valid_token_returns_claims():
    claims = _verifier().verify(_make({}))
    assert claims["sub"] == "user_1"


def test_wrong_issuer_rejected():
    with pytest.raises(TokenError):
        _verifier().verify(_make({"iss": "https://evil.example"}))


def test_expired_rejected():
    with pytest.raises(TokenError):
        _verifier().verify(_make({"exp": int(time.time()) - 3600}))


def test_alg_none_rejected():
    header = jwt.encode({"sub": "user_1"}, None, algorithm="none")
    with pytest.raises(TokenError):
        _verifier().verify(header)


def test_garbage_rejected():
    with pytest.raises(TokenError):
        _verifier().verify("not-a-jwt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/auth/test_jwt_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.auth.jwt_verifier'`.

- [ ] **Step 3: Write minimal implementation**

Add `pyjwt[crypto]>=2.8` to `backend/pyproject.toml` dependencies, `uv sync`.

```python
# backend/penny/auth/jwt_verifier.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt

from penny.auth.settings import AuthSettings


class TokenError(Exception):
    """The bearer token failed verification (maps to HTTP 401)."""


class ClerkJwtVerifier:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        signing_key_for: Callable[[str], Any] | None = None,
    ) -> None:
        self._settings = settings
        if signing_key_for is None:
            # JWKS URL from config — never derived from the token's iss claim.
            client = jwt.PyJWKClient(settings.jwks_url, cache_keys=True)
            signing_key_for = lambda tok: client.get_signing_key_from_jwt(tok).key  # noqa: E731
        self._signing_key_for = signing_key_for

    def verify(self, token: str) -> dict:
        try:
            key = self._signing_key_for(token)
            return jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._settings.issuer,
                audience=self._settings.audience,
                leeway=60,
                options={"verify_aud": self._settings.audience is not None},
            )
        except Exception as exc:  # any PyJWT error → uniform 401
            raise TokenError(str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/auth/test_jwt_verifier.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/auth/jwt_verifier.py backend/pyproject.toml backend/uv.lock \
  backend/tests/auth/test_jwt_verifier.py
git commit -m "feat(auth): Clerk JWT verifier (RS256, config-pinned issuer/JWKS)"
```

---

### Task 3: Identity linking (claims → users row)

**Files:**
- Create: `backend/penny/auth/identity.py`
- Test: `backend/tests/auth/test_identity.py`

**Interfaces:**
- Consumes: `User` model (phase 1a), verified claims (Task 2).
- Produces: `link_or_resolve_user(session, *, sub: str, email: str | None,
  email_verified: bool) -> tuple[uuid.UUID, uuid.UUID]` returning
  `(household_id, user_id)`. Resolution: (1) by `external_auth_id == sub`;
  (2) first-login link — requires `email_verified is True`, atomic
  `UPDATE users SET external_auth_id=:sub WHERE lower(email)=:email AND
  external_auth_id IS NULL`; (3) otherwise raise `UnknownUserError` (→ 403).
  *(Phase 4 later replaces branch 3 with auto-provision.)* Also defines
  `class AuthError(Exception)` base; `UnknownUserError(AuthError)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/auth/test_identity.py
import pytest

from penny.adapters.db.models import Household, User
from penny.auth.identity import UnknownUserError, link_or_resolve_user
from penny.db import get_db


def _seed_user(email: str, sub: str | None):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email=email, external_auth_id=sub)
        s.add(u)
        s.flush()
        return hh.household_id, u.user_id


def test_resolves_by_sub(isolated_db):
    hid, uid = _seed_user("a@x.com", "sub_1")
    with get_db().session() as s:
        assert link_or_resolve_user(s, sub="sub_1", email=None,
                                    email_verified=False) == (hid, uid)


def test_first_login_links_by_verified_email_case_insensitive(isolated_db):
    hid, uid = _seed_user("a@x.com", None)
    with get_db().session() as s:
        got = link_or_resolve_user(s, sub="sub_new", email="A@X.com",
                                   email_verified=True)
    assert got == (hid, uid)
    with get_db().session() as s:
        assert s.query(User).filter(User.user_id == uid).one().external_auth_id == "sub_new"


def test_unverified_email_cannot_link(isolated_db):
    _seed_user("a@x.com", None)
    with get_db().session() as s, pytest.raises(UnknownUserError):
        link_or_resolve_user(s, sub="sub_new", email="a@x.com", email_verified=False)


def test_unknown_user_rejected(isolated_db):
    _seed_user("a@x.com", "sub_1")
    with get_db().session() as s, pytest.raises(UnknownUserError):
        link_or_resolve_user(s, sub="stranger", email="who@x.com", email_verified=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/auth/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.auth.identity'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/auth/identity.py
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from penny.adapters.db.models import User


class AuthError(Exception):
    """Base for auth failures."""


class UnknownUserError(AuthError):
    """Authenticated identity has no matching users row (maps to HTTP 403)."""


def link_or_resolve_user(
    session: Session, *, sub: str, email: str | None, email_verified: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    by_sub = session.query(User).filter(User.external_auth_id == sub).one_or_none()
    if by_sub is not None:
        return by_sub.household_id, by_sub.user_id
    if email and email_verified:
        normalized = email.strip().lower()
        pending = (
            session.query(User)
            .filter(func.lower(User.email) == normalized,
                    User.external_auth_id.is_(None))
            .with_for_update()
            .one_or_none()
        )
        if pending is not None:
            pending.external_auth_id = sub  # atomic first-login link
            session.flush()
            logger.bind(user_id=str(pending.user_id)).info(
                "Linked Clerk subject to user on first login"
            )
            return pending.household_id, pending.user_id
    raise UnknownUserError(f"no user for subject {sub!r}")
```

(`with_for_update()` is a no-op on SQLite and row-locks on Postgres; the unique
constraint on `external_auth_id` is the hard backstop for the race.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/auth/test_identity.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/auth/identity.py backend/tests/auth/test_identity.py
git commit -m "feat(auth): identity linking (sub -> user, atomic verified-email first-login link)"
```

---

### Task 4: FastAPI dependency + route wiring + CORS

**Files:**
- Create: `backend/penny/api/auth.py`
- Modify: `backend/penny/api/main.py` (CORS at lines 35-40; dependency on
  `POST /api/chat` ~line 146 and `GET /api/sessions/{session_id}` ~line 132;
  startup validation in the existing startup hook ~line 29)
- Test: `backend/tests/api/test_auth_dependency.py`

**Interfaces:**
- Consumes: Tasks 1–3; phase-1a `resolve_dev_principal`, `set_request_context`,
  `reset_request_context`, `RequestContext`.
- Produces: generator dependency `request_context(request: Request) ->
  Iterator[RequestContext]` — clerk mode: bearer → `verify` → 
  `link_or_resolve_user` → ctx (401 `TokenError`/missing header; 403
  `UnknownUserError`); dev mode: env-pinned principal **only** (no headers).
  Sets the ContextVar before yield, resets in `finally`. Module-level
  `get_verifier()`/`get_auth_settings()` indirection so tests can override via
  `app.dependency_overrides` or monkeypatch.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_auth_dependency.py
import uuid

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

import penny.api.auth as api_auth
from penny.api.auth import request_context
from penny.auth.jwt_verifier import TokenError
from penny.auth.settings import AuthSettings
from penny.tenancy.context import RequestContext

CLERK = AuthSettings(mode="clerk", issuer="https://iss", jwks_url="https://iss/jwks",
                     audience=None, frontend_origin="https://app")


class FakeVerifier:
    def __init__(self, claims=None):
        self._claims = claims
    def verify(self, token):
        if self._claims is None:
            raise TokenError("bad token")
        return self._claims


def _app(monkeypatch, verifier, settings=CLERK):
    monkeypatch.setattr(api_auth, "get_auth_settings", lambda: settings)
    monkeypatch.setattr(api_auth, "get_verifier", lambda: verifier)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(ctx: RequestContext = Depends(request_context)):
        return {"user_id": str(ctx.user_id)}

    return app


def test_missing_bearer_is_401(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier()))
    assert client.get("/whoami").status_code == 401


def test_invalid_token_is_401(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier(claims=None)))
    r = client.get("/whoami", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_unknown_user_is_403(monkeypatch, isolated_db):
    from penny.db import get_db
    get_db().create_schema()
    verifier = FakeVerifier(claims={"sub": "stranger", "email": "s@x.com",
                                    "email_verified": True})
    client = TestClient(_app(monkeypatch, verifier))
    r = client.get("/whoami", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403


def test_clerk_mode_ignores_spoofed_dev_headers(monkeypatch, isolated_db):
    client = TestClient(_app(monkeypatch, FakeVerifier(claims=None)))
    r = client.get("/whoami", headers={
        "X-Penny-User-Id": str(uuid.uuid4()),
        "X-Penny-Household-Id": str(uuid.uuid4()),
    })
    assert r.status_code == 401  # headers do nothing without a valid bearer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_auth_dependency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.api.auth'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/penny/api/auth.py
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import HTTPException, Request

from penny.auth.identity import UnknownUserError, link_or_resolve_user
from penny.auth.jwt_verifier import ClerkJwtVerifier, TokenError
from penny.auth.settings import AuthSettings, load_auth_settings
from penny.db import get_db
from penny.tenancy.context import (
    RequestContext,
    reset_request_context,
    set_request_context,
)
from penny.tenancy.principal import resolve_dev_principal


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return load_auth_settings()


@lru_cache(maxsize=1)
def get_verifier() -> ClerkJwtVerifier:
    return ClerkJwtVerifier(get_auth_settings())


def _authenticate(request: Request) -> RequestContext:
    settings = get_auth_settings()
    if settings.mode == "dev":
        # Env-pinned principal ONLY — arbitrary headers are not honored.
        return resolve_dev_principal({})
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = get_verifier().verify(auth.split(" ", 1)[1])
    except TokenError:
        raise HTTPException(status_code=401, detail="invalid token") from None
    with get_db().session() as s:
        try:
            household_id, user_id = link_or_resolve_user(
                s,
                sub=str(claims.get("sub", "")),
                email=claims.get("email"),
                email_verified=bool(claims.get("email_verified", False)),
            )
        except UnknownUserError:
            raise HTTPException(status_code=403, detail="unknown user") from None
    return RequestContext(user_id=user_id, household_id=household_id)


def request_context(request: Request) -> Iterator[RequestContext]:
    ctx = _authenticate(request)
    token = set_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)
```

Then in `main.py`:
- Replace the CORS block (lines 35-40):

```python
_auth_settings = load_auth_settings()  # fail-closed at import/startup
_origins = ["http://localhost:5173"]
if _auth_settings.frontend_origin:
    _origins.append(_auth_settings.frontend_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

- Add `ctx: RequestContext = Depends(request_context)` to the `/api/chat` and
  `/api/sessions/{session_id}` handlers. `/api/health` stays public.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_auth_dependency.py -v` → PASS (4).
Also: `uv run pytest -q` → green (existing API tests updated to dev mode via
`PENNY_AUTH_MODE=dev` + `PENNY_DEV_*` in the `isolated_db`/test fixtures).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/api/auth.py backend/penny/api/main.py \
  backend/tests/api/test_auth_dependency.py
git commit -m "feat(api): auth dependency on all routes + CORS lockdown"
```

---

### Task 5: Conversation tenant columns + scoped store

**Files:**
- Modify: `backend/penny/api/persistence/models.py` (Conversation, lines 46-71)
- Modify: `backend/penny/api/persistence/store.py` (`ensure_conversation` lines
  50-55; `get_conversation_messages` lines 158-171; list/append/upsert)
- Test: `backend/tests/api/test_conversation_scoping.py`

**Interfaces:**
- Consumes: `RequestContext`, `SessionMode`.
- Produces: `Conversation` gains `household_id: Mapped[uuid.UUID]`,
  `owner_user_id: Mapped[uuid.UUID]`, `session_mode: Mapped[str]`
  (`'individual'`/`'joint'`, immutable). Store methods change to:
  - `ensure_conversation(conversation_id, ctx, *, session_mode: str = "individual")` —
    stamps tenant fields from `ctx` on create; validates `session_mode in
    ("individual", "joint")`; on an existing row verifies access (below) and
    **ignores** any client-supplied mode.
  - `get_conversation(conversation_id, ctx) -> Conversation` — raises
    `ConversationAccessError` unless `household_id == ctx.household_id and
    (owner_user_id == ctx.user_id or session_mode == "joint")`.
  - `get_conversation_messages(conversation_id, ctx)`, `append_user_message(...,
    ctx)`, `upsert_assistant_message(..., ctx)` — all call the access check first.
  - `ConversationAccessError(Exception)` → routes map it to **404**.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_conversation_scoping.py
import uuid

import pytest

from penny.api.persistence.store import ConversationAccessError, ConversationStore
from penny.tenancy.context import RequestContext, SessionMode

H1, H2 = uuid.uuid4(), uuid.uuid4()
A, B = uuid.uuid4(), uuid.uuid4()  # spouses in H1
STRANGER = uuid.uuid4()  # user in H2


def _ctx(uid, hid, mode=SessionMode.INDIVIDUAL):
    return RequestContext(user_id=uid, household_id=hid, session_mode=mode)


@pytest.fixture
def store(isolated_db):
    s = ConversationStore()
    s.create_schema()
    return s


def test_individual_thread_hidden_from_spouse(store):
    store.ensure_conversation("c1", _ctx(A, H1), session_mode="individual")
    with pytest.raises(ConversationAccessError):
        store.get_conversation("c1", _ctx(B, H1))


def test_joint_thread_visible_to_household_not_outsiders(store):
    store.ensure_conversation("c2", _ctx(A, H1), session_mode="joint")
    assert store.get_conversation("c2", _ctx(B, H1)).session_mode == "joint"
    with pytest.raises(ConversationAccessError):
        store.get_conversation("c2", _ctx(STRANGER, H2))


def test_owner_and_mode_come_from_ctx_and_are_immutable(store):
    store.ensure_conversation("c3", _ctx(A, H1), session_mode="individual")
    # Re-ensuring with a different mode does not mutate it.
    store.ensure_conversation("c3", _ctx(A, H1), session_mode="joint")
    assert store.get_conversation("c3", _ctx(A, H1)).session_mode == "individual"


def test_invalid_mode_rejected(store):
    with pytest.raises(ValueError):
        store.ensure_conversation("c4", _ctx(A, H1), session_mode="admin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_conversation_scoping.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConversationAccessError'` /
signature mismatch.

- [ ] **Step 3: Write minimal implementation**

In `models.py` add to `Conversation`:

```python
    household_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    session_mode: Mapped[str] = mapped_column(String, nullable=False,
                                              server_default=text("'individual'"))
```

**Web schema is Postgres, under RLS (series-review decision).** The web DB stops
being `create_all`-managed: add **migration `019_add_conversation_tenancy`** (the
web-schema migration set) that adds the three columns **and** enables the same
`tenant_isolation` policy (USING + WITH CHECK) + `FORCE ROW LEVEL SECURITY` on
`conversations`/`conversation_messages` (dialect-guarded). The
`ConversationStore` session must emit the same transaction-local
`set_config('app.current_household'/'app.current_user', …, true)` on the web-DB
connection (reuse the phase-1a `_apply_rls_settings` shape) so RLS binds. Local
SQLite dev gets the columns but no RLS (app-layer filter still applies). Prod
column backfill is owned by the phase-3 cutover (it assigns conversation
tenancy), not a one-off ALTER here.

In `store.py`:

```python
class ConversationAccessError(Exception):
    """Conversation exists but is not visible to this principal (route → 404)."""


_VALID_MODES = ("individual", "joint")


def _can_access(conv, ctx) -> bool:
    return conv.household_id == ctx.household_id and (
        conv.owner_user_id == ctx.user_id or conv.session_mode == "joint"
    )
```

`ensure_conversation(self, conversation_id, ctx, *, session_mode="individual")`:
validate mode ∈ `_VALID_MODES` (else `ValueError`); if the row exists, check
`_can_access` (raise `ConversationAccessError`) and return; else insert with
`household_id=ctx.household_id, owner_user_id=ctx.user_id,
session_mode=session_mode`. Every read/write method loads the row, applies
`_can_access` (missing row → also `ConversationAccessError`, so 404 hides
existence), then proceeds. Conversation listings filter with the same predicate
translated to SQL: `household_id == ctx.household AND (owner_user_id ==
ctx.user OR session_mode == 'joint')`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_conversation_scoping.py -v` → PASS (4).
Full suite green (`uv run pytest -q`) after updating existing store call sites.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/api/persistence/models.py backend/penny/api/persistence/store.py \
  backend/tests/api/test_conversation_scoping.py
git commit -m "feat(conversations): tenant columns + access-checked store (mode immutable)"
```

---

### Task 6: `/api/chat` turn context from the conversation's mode

**Files:**
- Modify: `backend/penny/api/main.py` (chat handler, lines 146-181)
- Modify: `backend/penny/api/bridge.py` (`stream_and_persist`, lines 189-256 —
  pass `ctx` through to `_safe_persist`/store calls)
- Test: `backend/tests/api/test_chat_turn_context.py`

**Interfaces:**
- Consumes: Tasks 4–5; phase-1a `set_request_context` and the ContextVar.
- Produces: the chat handler (a) reads optional `body["sessionMode"]` **only for
  creation** of a new conversation, (b) calls `store.ensure_conversation(chat_id,
  ctx, session_mode=requested)`, (c) rebuilds the turn context as
  `replace(ctx, session_mode=SessionMode(conv.session_mode))` and re-sets the
  ContextVar for the duration of the stream (reset in the stream's `finally`),
  so a joint conversation runs RLS with the nil sentinel. `ConversationAccessError`
  → `HTTPException(404)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_chat_turn_context.py
import uuid

from penny.api.main import _turn_context  # small pure helper extracted for testability
from penny.tenancy.context import RequestContext, SessionMode


def test_turn_context_adopts_conversation_mode():
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    turn = _turn_context(ctx, conversation_mode="joint")
    assert turn.session_mode is SessionMode.JOINT
    assert turn.user_id == ctx.user_id and turn.household_id == ctx.household_id


def test_turn_context_defaults_individual():
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    assert _turn_context(ctx, conversation_mode="individual").session_mode is SessionMode.INDIVIDUAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_chat_turn_context.py -v`
Expected: FAIL — `ImportError: cannot import name '_turn_context'`.

- [ ] **Step 3: Write minimal implementation**

In `main.py`:

```python
from dataclasses import replace

from penny.tenancy.context import RequestContext, SessionMode


def _turn_context(ctx: RequestContext, *, conversation_mode: str) -> RequestContext:
    return replace(ctx, session_mode=SessionMode(conversation_mode))
```

In the chat handler: `requested = str(body.get("sessionMode") or "individual")`;
`conv = store.ensure_conversation(chat_id, ctx, session_mode=requested)` (in a
`try/except ConversationAccessError: raise HTTPException(404)`); build
`turn_ctx = _turn_context(ctx, conversation_mode=conv.session_mode)`; wrap the
streaming generator so it does `token = set_request_context(turn_ctx)` before
iterating and `reset_request_context(token)` in `finally` (the dependency's
outer token still resets after the response). Pass `turn_ctx` into
`stream_and_persist(..., ctx=turn_ctx)` and thread it to the store persistence
calls added in Task 5.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_chat_turn_context.py -v` → PASS.
Full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/api/main.py backend/penny/api/bridge.py \
  backend/tests/api/test_chat_turn_context.py
git commit -m "feat(chat): per-turn RequestContext adopts the conversation's stored mode"
```

---

### Task 7: `run_sql` read-only role

**Files:**
- Modify: `backend/penny/tools/analytics.py` (the `run_sql` tool)
- Modify: `backend/penny/db.py` (add `get_readonly_db()`)
- Modify: `backend/.env.example`
- Test: `backend/tests/tools/test_run_sql_readonly.py` (Postgres-marked)

**Interfaces:**
- Produces: `get_readonly_db() -> DB` — a second `DB` bound to
  `PENNY_AGENT_READONLY_DATABASE_URL` when set; falls back to the primary URL
  **only in dev mode** (SQLite has no roles), and raises at startup in clerk
  mode if unset. `run_sql` executes on the read-only DB via
  `session_for(require_request_context())`, so RLS settings still apply on the
  read-only role's connection. One-time role DDL (run manually on Neon,
  documented in `.env.example`):

```sql
CREATE ROLE penny_agent_ro LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO penny_agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO penny_agent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO penny_agent_ro;
```

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/tools/test_run_sql_readonly.py
import pytest

pytestmark = pytest.mark.postgres

# Using pg_db + a penny_agent_ro-style role URL (POSTGRES_TEST_RO_URL), assert:
# 1. SELECT through the read-only connection under a RequestContext succeeds and
#    is RLS-scoped (household A sees only A rows).
# 2. INSERT/UPDATE/DELETE through it fail with a permission error.
```

Implement with two contexts against seeded households (mirror the phase-1a
`test_rls_isolation.py` seed): run `SELECT count(*)` (succeeds, scoped) and
`INSERT INTO plaid_transactions ...` / `DELETE FROM plaid_transactions` (each
`pytest.raises` a `sqlalchemy.exc.ProgrammingError` wrapping
`InsufficientPrivilege`). Skip when `POSTGRES_TEST_RO_URL` is unset.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && POSTGRES_TEST_URL=<url> POSTGRES_TEST_RO_URL=<ro-url> uv run pytest tests/tools/test_run_sql_readonly.py -v`
Expected: FAIL — `get_readonly_db` missing / DML unexpectedly succeeds.

- [ ] **Step 3: Write minimal implementation**

In `db.py`:

```python
_readonly_db: DB | None = None


def get_readonly_db() -> DB:
    """DB handle for the agent's free-form run_sql — read-only role in prod."""
    global _readonly_db
    if _readonly_db is None:
        url = os.environ.get("PENNY_AGENT_READONLY_DATABASE_URL", "").strip()
        if not url:
            from penny.auth.settings import load_auth_settings
            if load_auth_settings().mode == "clerk":
                raise RuntimeError(
                    "PENNY_AGENT_READONLY_DATABASE_URL is required in clerk mode"
                )
            return get_db()  # dev/SQLite fallback
        _readonly_db = DB(url)
    return _readonly_db
```

In `analytics.py`, switch `run_sql`'s session acquisition from `get_db()` to
`get_readonly_db().session_for(require_request_context())`. Reset the singleton
in the tests' `_reset_singletons` helper. Document the role DDL + env var in
`.env.example`.

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2 → PASS; suite skips cleanly without the env vars.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/db.py backend/penny/tools/analytics.py backend/.env.example \
  backend/tests/tools/test_run_sql_readonly.py
git commit -m "feat(security): run_sql executes on a read-only role (RLS still applies)"
```

---

### Task 8: `send_email_report` — no recipient parameter

**Files:**
- Modify: `backend/penny/tools/delivery.py`
- Test: `backend/tests/tools/test_delivery_recipients.py`

**Interfaces:**
- Consumes: `require_request_context`, `NIL_USER_UUID`, `User` model, the
  existing email-sending internals (Resend).
- Produces: `resolve_report_recipients(session, ctx) -> list[str]` — individual
  mode → `[that user's email]`; joint mode (`effective_user_id == NIL_USER_UUID`)
  → all emails in `ctx.household_id` with `external_auth_id IS NOT NULL`
  (pending invitees excluded). The `send_email_report` **tool signature drops
  `to`** — any `to` argument ceases to exist; the tool derives recipients
  internally. The cron prompt builder (`cli.py `_build_prompt`) stops embedding
  addresses in prompt text.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/tools/test_delivery_recipients.py
import inspect
import uuid

from penny.adapters.db.models import Household, User
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode
from penny.tools.delivery import resolve_report_recipients, send_email_report


def _seed():
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        a = User(household_id=hh.household_id, email="a@x.com", external_auth_id="c1")
        b = User(household_id=hh.household_id, email="b@x.com", external_auth_id="c2")
        pending = User(household_id=hh.household_id, email="p@x.com",
                       external_auth_id=None)
        s.add_all([a, b, pending])
        s.flush()
        return hh.household_id, a.user_id


def test_individual_mode_emails_only_that_user(isolated_db):
    hid, uid = _seed()
    ctx = RequestContext(user_id=uid, household_id=hid)
    with get_db().session() as s:
        assert resolve_report_recipients(s, ctx) == ["a@x.com"]


def test_joint_mode_emails_active_household_members(isolated_db):
    hid, uid = _seed()
    ctx = RequestContext(user_id=uid, household_id=hid,
                         session_mode=SessionMode.JOINT)
    with get_db().session() as s:
        assert sorted(resolve_report_recipients(s, ctx)) == ["a@x.com", "b@x.com"]


def test_tool_has_no_recipient_parameter():
    assert "to" not in inspect.signature(send_email_report).parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/tools/test_delivery_recipients.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_report_recipients'`
and/or the `to` parameter still present.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/tools/delivery.py
from penny.adapters.db.models import User
from penny.tenancy.context import RequestContext, SessionMode


def resolve_report_recipients(session, ctx: RequestContext) -> list[str]:
    if ctx.session_mode is SessionMode.JOINT:
        rows = (
            session.query(User)
            .filter(User.household_id == ctx.household_id,
                    User.external_auth_id.isnot(None))
            .all()
        )
        return [r.email for r in rows]
    row = session.query(User).filter(User.user_id == ctx.user_id).one()
    return [row.email]
```

Change the `send_email_report` `@tool` signature to drop `to: list[str]`; inside,
`ctx = require_request_context()` and
`recipients = resolve_report_recipients(session, ctx)` (identity tables are not
RLS-scoped, so a plain session works); pass `recipients` to the existing send
call. Remove the "email it to the following recipient(s)" text from
`cli.py `_build_prompt` and the `--email` plumbing that fed it (superseded by
Task 9's job model).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/tools/test_delivery_recipients.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/tools/delivery.py backend/penny/cli.py \
  backend/tests/tools/test_delivery_recipients.py
git commit -m "feat(security): send_email_report derives recipients from auth ctx (no to param)"
```

---

### Task 9: Cron principal — explicit context, fail loudly

**Files:**
- Modify: `backend/penny/cli.py` (`_drive_agent` lines 87-127,
  `run-scheduled-report` lines 142-174)
- Test: `backend/tests/test_cron_context.py`

**Interfaces:**
- Produces: `load_cron_jobs() -> list[CronJob]` where
  `@dataclass(frozen=True) CronJob(ctx: RequestContext, kind: str)` —
  built from `PENNY_CRON_HOUSEHOLD_ID` (uuid) and `PENNY_CRON_USER_IDS`
  (comma-separated uuids). Yields one `individual` job per user
  (`ctx = RequestContext(user, household)`) plus one `household` job
  (`ctx = RequestContext(first_user, household, session_mode=JOINT)`).
  Raises `RuntimeError` when either env var is unset/empty — cron never runs
  unscoped. `_drive_agent` gains a required `ctx: RequestContext` keyword and
  wraps `agent.run` with `set_request_context(ctx)` / `reset` in `finally`;
  `run-scheduled-report` iterates the jobs, one agent run per job.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cron_context.py
import uuid

import pytest

from penny.cli import load_cron_jobs
from penny.tenancy.context import SessionMode

H = str(uuid.uuid4())
U1, U2 = str(uuid.uuid4()), str(uuid.uuid4())


def test_jobs_cover_each_user_plus_household(monkeypatch):
    monkeypatch.setenv("PENNY_CRON_HOUSEHOLD_ID", H)
    monkeypatch.setenv("PENNY_CRON_USER_IDS", f"{U1},{U2}")
    jobs = load_cron_jobs()
    kinds = [(j.kind, j.ctx.session_mode) for j in jobs]
    assert kinds == [
        ("individual", SessionMode.INDIVIDUAL),
        ("individual", SessionMode.INDIVIDUAL),
        ("household", SessionMode.JOINT),
    ]
    assert {str(j.ctx.user_id) for j in jobs if j.kind == "individual"} == {U1, U2}


def test_missing_principal_fails_loudly(monkeypatch):
    monkeypatch.delenv("PENNY_CRON_HOUSEHOLD_ID", raising=False)
    monkeypatch.delenv("PENNY_CRON_USER_IDS", raising=False)
    with pytest.raises(RuntimeError):
        load_cron_jobs()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_cron_context.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_cron_jobs'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/penny/cli.py
import os
import uuid as _uuid
from dataclasses import dataclass

from penny.tenancy.context import RequestContext, SessionMode


@dataclass(frozen=True, slots=True)
class CronJob:
    ctx: RequestContext
    kind: str  # "individual" | "household"


def load_cron_jobs() -> list[CronJob]:
    hh_raw = os.environ.get("PENNY_CRON_HOUSEHOLD_ID", "").strip()
    users_raw = os.environ.get("PENNY_CRON_USER_IDS", "").strip()
    if not hh_raw or not users_raw:
        raise RuntimeError(
            "cron requires PENNY_CRON_HOUSEHOLD_ID and PENNY_CRON_USER_IDS — "
            "refusing to run without a tenant principal"
        )
    household = _uuid.UUID(hh_raw)
    user_ids = [_uuid.UUID(u.strip()) for u in users_raw.split(",") if u.strip()]
    jobs = [
        CronJob(ctx=RequestContext(user_id=u, household_id=household), kind="individual")
        for u in user_ids
    ]
    jobs.append(
        CronJob(
            ctx=RequestContext(user_id=user_ids[0], household_id=household,
                               session_mode=SessionMode.JOINT),
            kind="household",
        )
    )
    return jobs
```

In `_drive_agent`, add the `ctx` keyword and the ContextVar set/reset around
`agent.run`. In `run-scheduled-report`, `for job in load_cron_jobs(): await
_drive_agent(prompt_text=..., max_turns=..., ctx=job.ctx)` (individual jobs use
the personal-report prompt; the household job uses the shared-report prompt).
Recipients are already derived from `ctx` by Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_cron_context.py -v` → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/cli.py backend/tests/test_cron_context.py
git commit -m "feat(cron): explicit per-job RequestContext, fail-loud principal"
```

---

### Task 10: Frontend — Clerk gate, bearer transport, mode picker

**Files:**
- Create: `frontend/src/AuthGate.tsx`
- Modify: `frontend/src/main.tsx` (wrap in `<ClerkProvider>`)
- Modify: `frontend/src/ChatScreen.tsx` (transport at lines 22-36; sessions
  fetch at ~line 100; new-chat mode picker)
- Modify: `frontend/package.json` (`@clerk/clerk-react`), `frontend/.env.example`
  (`VITE_CLERK_PUBLISHABLE_KEY`)
- Test: manual (no frontend test harness in this repo).

**Interfaces:**
- Consumes: backend 401/403 semantics (Task 4), `sessionMode` body field (Task 6).
- Produces: authenticated shell; every API call carries
  `Authorization: Bearer <await getToken()>`.

- [ ] **Step 1: Install + provider**

`npm install @clerk/clerk-react`. In `main.tsx`, wrap the root in
`<ClerkProvider publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}>`.

- [ ] **Step 2: Auth gate**

```tsx
// frontend/src/AuthGate.tsx
import { SignedIn, SignedOut, SignIn, UserButton } from "@clerk/clerk-react";
import type { ReactNode } from "react";

export function AuthGate({ children }: { children: ReactNode }) {
  return (
    <>
      <SignedOut>
        <div className="auth-gate">
          <SignIn routing="hash" />
        </div>
      </SignedOut>
      <SignedIn>
        <header className="auth-header">
          <UserButton />
        </header>
        {children}
      </SignedIn>
    </>
  );
}
```

- [ ] **Step 3: Bearer on the transport + sessions fetch, and the mode picker**

In `ChatScreen.tsx`: get `const { getToken } = useAuth()`. Extend
`makeTransport` so `prepareSendMessagesRequest` returns
`{ body: { ...current, sessionMode }, headers: { Authorization: `Bearer ${await getToken()}` } }`
(the AI SDK supports async `prepareSendMessagesRequest`); add the same header to
the `/api/sessions/{id}` fetch. Add a new-chat control offering
**Individual | Joint** that sets `sessionMode` for the conversation's first
message (default `individual`); existing conversations don't show the picker
(the mode is immutable server-side). Replace the `penny:sessionId` localStorage
bootstrapping with a server-scoped conversation list where applicable.

- [ ] **Step 4: Manual verification**

Backend running in clerk mode with Clerk dev keys; `npm run dev`. Verify:
signed-out → Clerk sign-in; after Google sign-in the chat loads; a request with
DevTools-stripped header fails 401; a joint conversation answers shared-only
data; an individual one includes private data.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/AuthGate.tsx frontend/src/main.tsx frontend/src/ChatScreen.tsx \
  frontend/package.json frontend/package-lock.json frontend/.env.example
git commit -m "feat(frontend): Clerk auth gate, bearer transport, per-conversation mode picker"
```

---

### Task 11: Phase-1a amendments (WITH CHECK + nil-uuid CHECK)

The two security-review findings recorded in the spec's "Amendments to phase 1a".
**Because phase 1a is not yet built, these fold directly into phase-1a's
migrations `010`/`011` — they do NOT get their own revision** (so `014` stays
free for phase-1b's workspace store per the migration ledger). This task is the
verification that the fold happened, not a new migration.

**Files:**
- Modify: `docs/superpowers/plans/2026-06-27-phase-1a-multi-tenant-data-model.md`
  (Tasks 7 and 10) — add `WITH CHECK (<same predicate as USING>)` to every
  `tenant_isolation` policy in migration `011`, and
  `CHECK (owner_user_id <> nil-uuid)` in migration `010`. No standalone
  amendment migration.
- Test: covered by phase-1a's acceptance suite test 5
  (`test_write_cannot_set_foreign_household_id`) plus a new nil-uuid case.

**Interfaces:**
- Produces: every `tenant_isolation` policy gains
  `WITH CHECK ( <same predicate as USING> )`; every owner/visibility table gains
  `CHECK (owner_user_id <> '00000000-0000-0000-0000-000000000000')`
  (named `ck_<table>_owner_not_nil`); the backfill (migration 009) is asserted
  never to write the nil UUID.

- [ ] **Step 1:** Confirm the `WITH CHECK` clause and the nil-uuid `CHECK` are
  folded into phase-1a migrations `011`/`010` (no standalone amendment
  migration), using the exact predicate from phase-1a migration `011` for the
  `WITH CHECK` clause.
- [ ] **Step 2:** Extend the phase-1a acceptance battery with
  `test_joint_sentinel_never_matches_a_real_row` — inserting a row with the nil
  owner UUID raises `IntegrityError`.
- [ ] **Step 3:** Run: `cd backend && POSTGRES_TEST_URL=<url> uv run pytest -m postgres -q` → green.
- [ ] **Step 4: Commit**

```bash
git add backend/db/migrations backend/tests docs/superpowers/plans/2026-06-27-phase-1a-multi-tenant-data-model.md
git commit -m "feat(db): RLS WITH CHECK + nil-uuid owner guard (phase-1a amendments)"
```

---

### Task 12: End-to-end auth battery

**Files:**
- Create: `backend/tests/api/test_auth_e2e.py`

**Interfaces:** consumes everything above via the FastAPI app (`TestClient`,
verifier faked as in Task 4).

- [ ] **Step 1: Write the battery** — concrete tests, each seeding via
  `isolated_db` + `create_schema` and hitting the real routes:

```python
# backend/tests/api/test_auth_e2e.py — test names and assertions:
# test_chat_without_token_401
# test_chat_with_invalid_token_401
# test_chat_unknown_user_403
# test_sessions_endpoint_requires_auth_401
# test_sessions_cross_user_conversation_404      (IDOR: A's individual thread via B's token)
# test_sessions_cross_household_conversation_404 (IDOR across households)
# test_joint_conversation_readable_by_spouse_200
# test_session_mode_from_body_ignored_on_existing_conversation
# test_health_stays_public_200
```

Each uses two fake principals (spouses A/B in H1, stranger S in H2) by seeding
`users` rows and faking verifier claims per request (`sub_a`/`sub_b`/`sub_s`).

- [ ] **Step 2–3:** Run `cd backend && uv run pytest tests/api/test_auth_e2e.py -v`,
  implement/fix until all pass; then the full gate (`ruff` + `pytest -q`).
- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_auth_e2e.py
git commit -m "test(auth): end-to-end 401/403/404 + IDOR + spoof battery"
```

---

## Browser E2E Validation (Playwright)

Automated, headless-CI-able Playwright specs under `frontend/e2e/*.spec.ts`,
running against the live backend + frontend (dev servers or the CI-built
preview) and reusing the shared e2e harness bootstrapped in phase 1a
(fixtures, seeded households/users, base URL, global setup/teardown). These
cover what the backend `TestClient` battery (Task 12) cannot: the Clerk sign-in
flow, the rendered chat, and cross-user isolation in a real browser.

**Clerk in tests uses Clerk's testing tokens / test mode** for programmatic
sign-in — no interactive Google OAuth. This phase adds a
`signInAsTestUser(page, user)` helper to the shared harness (built on
`@clerk/testing`'s Playwright utilities + a Clerk test-mode session), reused by
phases 4 and 5. Test users map to the seeded `users` rows (A and B in household
H1) so conversation scoping is exercised end-to-end.

**Env/setup:** `frontend/e2e/` gains a `playwright.config.ts` (or extends the
phase-1a shared config) pointing `baseURL` at the running frontend and a
`webServer`/global-setup that ensures backend (clerk mode with Clerk **test**
keys) + frontend are up and the DB is seeded. Clerk test keys and
`CLERK_SECRET_KEY` come from CI secrets; `signInAsTestUser` obtains a testing
token via `@clerk/testing` before navigating.

---

### Task 13: E2E harness — `signInAsTestUser` + auth flow spec

**Files:**
- Create: `frontend/e2e/support/auth.ts` — `signInAsTestUser(page, user)` helper
  (added to the shared harness; reused by phases 4 and 5).
- Create: `frontend/e2e/auth.spec.ts`
- Modify: `frontend/e2e/playwright.config.ts` (or the phase-1a shared config) and
  `frontend/package.json` (add `@playwright/test`, `@clerk/testing`; `e2e` script).

**Interfaces:**
- Produces: `signInAsTestUser(page: Page, user: TestUser): Promise<void>` —
  injects a Clerk testing token and establishes a test-mode session for the given
  seeded user, then waits for the chat shell to render.
- Consumes: the phase-1a shared e2e fixtures (seeded households/users, base URL).

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/auth.spec.ts
import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A } from "./support/auth";

test("signed-out user sees the Clerk sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /message/i })).toHaveCount(0);
});

test("sign in, send a message, get a response, sign out", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await expect(page.getByRole("textbox", { name: /message/i })).toBeVisible();

  await page.getByRole("textbox", { name: /message/i }).fill("How much did I spend?");
  await page.getByRole("button", { name: /send/i }).click();
  await expect(page.locator("[data-message-role='assistant']").last()).toBeVisible();

  await page.getByRole("button", { name: /account|user menu/i }).click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});

test("a protected request while signed-out is rejected (no chat access)", async ({ page }) => {
  const res = await page.request.post("/api/chat", {
    data: { messages: [], sessionMode: "individual" },
  });
  expect([401, 403]).toContain(res.status());
});
```

- [ ] **Step 2: Run the spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/auth.spec.ts`
Expected: FAIL — no `signInAsTestUser` helper / sign-in flow not yet wired.

- [ ] **Step 3: Implement the harness helper + enable the spec**

Add `frontend/e2e/support/auth.ts` with `signInAsTestUser` (Clerk testing token
via `@clerk/testing/playwright`, navigate to `/`, wait for the composer). Define
`USER_A`/`USER_B` mapped to the seeded rows. Wire `playwright.config.ts`
(`baseURL`, `webServer`/global-setup starting backend in clerk **test** mode +
frontend, seeding the DB). Ensure the signed-out and protected-request
assertions pass against the Task 4/Task 10 behavior.

- [ ] **Step 4: Run the spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/auth.spec.ts` → PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/support/auth.ts frontend/e2e/auth.spec.ts \
  frontend/e2e/playwright.config.ts frontend/package.json frontend/package-lock.json
git commit -m "test(e2e): Clerk test-mode sign-in helper + auth flow spec"
```

---

### Task 14: E2E — session-mode picker

**Files:**
- Create: `frontend/e2e/session-mode.spec.ts`

**Interfaces:** consumes `signInAsTestUser` (Task 13) and the Task 10 new-chat
mode picker + Task 5/6 persistence.

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/session-mode.spec.ts
import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A } from "./support/auth";

test("new-chat picker offers Individual and Joint", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await page.getByRole("button", { name: /new chat/i }).click();
  await expect(page.getByRole("radio", { name: /individual/i })).toBeVisible();
  await expect(page.getByRole("radio", { name: /joint|household/i })).toBeVisible();
});

test("creating a joint conversation persists that mode", async ({ page }) => {
  await signInAsTestUser(page, USER_A);
  await page.getByRole("button", { name: /new chat/i }).click();
  await page.getByRole("radio", { name: /joint|household/i }).check();
  await page.getByRole("textbox", { name: /message/i }).fill("Household summary");
  await page.getByRole("button", { name: /send/i }).click();
  await expect(page.locator("[data-message-role='assistant']").last()).toBeVisible();

  // Mode is immutable server-side: reloading the conversation keeps it joint and
  // no longer offers the picker.
  await page.reload();
  await expect(page.getByText(/joint|household/i)).toBeVisible();
  await expect(page.getByRole("radio", { name: /individual/i })).toHaveCount(0);
});
```

- [ ] **Step 2: Run the spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/session-mode.spec.ts`
Expected: FAIL — picker/persistence not yet wired.

- [ ] **Step 3: Implement/enable**

Ensure the Task 10 picker exposes accessible `radio` roles for
Individual/Joint, sends `sessionMode` on the first message, and that an existing
conversation renders its stored mode (and hides the picker). No new backend
work — this validates Tasks 5, 6, and 10 through the browser.

- [ ] **Step 4: Run the spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/session-mode.spec.ts` → PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/session-mode.spec.ts
git commit -m "test(e2e): session-mode picker offers + persists Individual/Joint"
```

---

### Task 15: E2E — conversation isolation across users

**Files:**
- Create: `frontend/e2e/conversation-isolation.spec.ts`

**Interfaces:** consumes `signInAsTestUser` (Task 13) and the Task 5 scoped
store (`ConversationAccessError` → 404).

- [ ] **Step 1: Write the failing spec**

```ts
// frontend/e2e/conversation-isolation.spec.ts
import { expect, test } from "@playwright/test";
import { signInAsTestUser, USER_A, USER_B } from "./support/auth";

test("user B cannot open user A's individual conversation URL", async ({ browser }) => {
  // Context A: create an individual conversation, capture its id/URL.
  const ctxA = await browser.newContext();
  const pageA = await ctxA.newPage();
  await signInAsTestUser(pageA, USER_A);
  await pageA.getByRole("textbox", { name: /message/i }).fill("Private note");
  await pageA.getByRole("button", { name: /send/i }).click();
  await expect(pageA.locator("[data-message-role='assistant']").last()).toBeVisible();
  const privateUrl = pageA.url(); // /c/<conversation-id>

  // Context B: a different signed-in user cannot open A's individual thread.
  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  await signInAsTestUser(pageB, USER_B);
  await pageB.goto(privateUrl);
  await expect(pageB.getByText(/not found|no access|404/i)).toBeVisible();
  await expect(pageB.locator("[data-message-role='assistant']")).toHaveCount(0);

  await ctxA.close();
  await ctxB.close();
});
```

- [ ] **Step 2: Run the spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/conversation-isolation.spec.ts`
Expected: FAIL — until scoping + a not-found route render are wired.

- [ ] **Step 3: Implement/enable**

Rely on the Task 5 store returning 404 for a conversation the principal can't
access; ensure the frontend renders a not-found/blocked state (not an empty
chat) for that response. Two `browser.newContext()` instances give the two users
independent Clerk test sessions.

- [ ] **Step 4: Run the spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/conversation-isolation.spec.ts` → PASS.
Also run the whole browser suite headless:
`cd frontend && npx playwright test` → green.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/conversation-isolation.spec.ts
git commit -m "test(e2e): cross-user conversation isolation (B blocked from A's thread)"
```

---

## Modularization

Structured so the auth core can be lifted into a standalone package with no
Penny-specific coupling. Only genuinely clean boundaries are called out — no
premature abstraction.

**Clerk auth kit for FastAPI.** The reusable unit is the `penny/auth/` core plus
the `penny/api/auth.py` dependency: fail-closed `AuthSettings` /
`load_auth_settings()` (Task 1), the `ClerkJwtVerifier` (RS256, config-pinned
issuer/JWKS, `iss`/`exp`/`aud`/`alg` all verified against config never the token
— Task 2), and the FastAPI `request_context` dependency that turns a bearer
token into an authenticated identity and manages the ContextVar lifecycle
(Task 4).

- **Seam / interface:** the kit's output is a `RequestContext` (the phase-1a
  tenancy toolkit consumes it downstream). Auth *produces* the context; tenancy
  *enforces* on it — so the two compose without coupling. Inputs are the
  `AuthSettings` dataclass and the injectable `signing_key_for` /
  `get_verifier()` / `get_auth_settings()` indirection (already used by the
  tests via `app.dependency_overrides`), which is exactly the injection seam an
  external consumer needs.
- **Keep OUT (Penny coupling):** the `users`-table specifics live behind a small
  resolver interface. Today `link_or_resolve_user` (Task 3) reaches straight into
  Penny's `User` model; the portable boundary is a `sub`/`email` →
  `(tenant_id, user_id)` resolver callable that another app supplies with its own
  user lookup. Also keep out: the `PENNY_*` env-var names (pass an
  `AuthSettings` in rather than reading `os.environ`), the conversation store,
  `run_sql`, email/cron wiring, and the `NIL_USER_UUID` joint-mode sentinel —
  all of those are Penny/tenancy concerns, not auth.
- **Portable to:** any FastAPI + Clerk app that needs verified-JWT request auth
  yielding a per-request identity context.

---

## Self-Review

**Spec coverage:** fail-closed settings → Task 1; JWT verification (JWKS from
config, iss/exp/aud/alg) → Task 2; email-verified atomic linking → Task 3;
dependency + ContextVar + 401/403 + clerk-ignores-headers + CORS → Task 4;
conversation columns, visibility-from-mode, immutability, owner-from-ctx →
Task 5; turn context from stored mode + nil-sentinel joint → Task 6; read-only
`run_sql` → Task 7; no-recipient email tool → Task 8; cron explicit principal +
two job kinds → Task 9; frontend (provider, in-memory tokens via Clerk default,
bearer, mode picker) → Task 10; phase-1a amendments (`WITH CHECK`, nil-uuid
CHECK) → Task 11; testing strategy → Tasks 1–9 unit + Task 12 battery. Token
storage note: Clerk's React SDK keeps session tokens in memory and refreshes via
its Frontend API — Task 10 must not add any localStorage token caching.

**Placeholder scan:** Tasks 7 (Postgres RO test), 11, and 12 specify test
*batteries* by exact name + assertion in comments rather than full bodies —
each names its seed pattern and expected error type; all service/route code is
concrete. No TBD/TODO.

**Type consistency:** `AuthSettings`, `ClerkJwtVerifier.verify`, `TokenError`,
`AuthError`/`UnknownUserError`, `link_or_resolve_user(...) -> (household_id,
user_id)`, `request_context` dependency, `ensure_conversation(conversation_id,
ctx, *, session_mode)`, `ConversationAccessError`, `_turn_context`,
`get_readonly_db`, `resolve_report_recipients`, `CronJob`/`load_cron_jobs` are
used consistently; phase-1a names (`RequestContext`, `SessionMode`,
`set_request_context`/`reset_request_context`, `session_for`,
`require_request_context`, `NIL_USER_UUID`) match the phase-1a plan.

## Execution Handoff

Execute **after phase 1a** (it consumes `penny.tenancy` and the tenant columns).
Phase 4's plan then replaces Task 3's unknown-user branch with auto-provision.
Subagent-driven execution recommended for Tasks 1–9, 11–12; Task 10 is a
frontend task verified manually with Clerk dev keys. Postgres tasks (7, 11, 12's
RLS-adjacent cases) need `POSTGRES_TEST_URL` (and 7 `POSTGRES_TEST_RO_URL`) on
the Neon `penny-test` branch.
