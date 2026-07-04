"""FastAPI request-auth dependency: bearer token -> ``RequestContext``.

This is the website→agent seam for identity. In ``clerk`` mode it verifies the
``Authorization: Bearer`` JWT (config-pinned issuer/JWKS), links it to a
``users`` row, and yields the phase-1a ``RequestContext`` — setting the
tenancy ContextVar for the request and resetting it after. Missing/invalid
token → 401; authenticated-but-unknown user → 403. In ``dev`` mode it resolves
an **env-pinned** principal only (``PENNY_DEV_*``); arbitrary ``X-Penny-*``
headers are never honored, so a spoofed header cannot forge identity.

``get_auth_settings`` / ``get_verifier`` are module-level indirections so tests
can override them via ``app.dependency_overrides`` or monkeypatch.
"""

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
        try:
            reset_request_context(token)
        except ValueError:
            # A streaming response / threaded ASGI test client can finalize the
            # dependency in a different context than the one that set the token
            # (token.reset then raises). Clear instead, so no principal leaks
            # past the request.
            set_request_context(None)
