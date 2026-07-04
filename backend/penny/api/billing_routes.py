"""Website API routes for BYO credentials, billing, and provider OAuth.

Website-domain surface over the ``penny.billing`` metered-BYOK module. Every
route is authed (``request_context``) and owner-scoped through the
``BillingSession``. Secrets are write-only here: an API key is accepted on POST
but **never** returned (reads expose only the masked hint).

Mounted on the app by ``penny.api.main``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from penny.auth.settings import load_auth_settings
from penny.billing import oauth, vault
from penny.billing.oauth import OAuthError
from penny.billing.session import BillingSession
from penny.tenancy.context import RequestContext

from .auth import request_context

router = APIRouter()


class ApiKeyBody(BaseModel):
    provider: str = Field(min_length=1)
    key: str = Field(min_length=1)


@router.post("/api/providers/{provider}/key")
def connect_api_key(
    provider: str,
    body: ApiKeyBody,
    ctx: RequestContext = Depends(request_context),
) -> dict[str, str]:
    """Store (or replace) the user's API key for ``provider``.

    The key is accepted once and encrypted at rest; it is never echoed back.
    """
    if body.provider != provider:
        raise HTTPException(status_code=400, detail="provider mismatch")
    with BillingSession().begin(ctx) as s:
        vault.upsert_api_key(s, ctx, provider=provider, key=body.key)
    return {"status": "connected", "provider": provider}


@router.delete("/api/providers/{provider}")
def disconnect_provider(
    provider: str,
    ctx: RequestContext = Depends(request_context),
) -> dict[str, str]:
    """Remove the user's credential for ``provider`` (idempotent)."""
    with BillingSession().begin(ctx) as s:
        vault.remove(s, ctx, provider=provider)
    return {"status": "disconnected", "provider": provider}


@router.get("/api/providers/{provider}/oauth/start")
def oauth_start(
    provider: str,
    ctx: RequestContext = Depends(request_context),
) -> dict[str, str]:
    """Begin a sanctioned OAuth flow — returns the provider ``authorize_url``."""
    try:
        with BillingSession().begin(ctx) as s:
            return oauth.start(s, ctx, provider=provider)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/providers/{provider}/oauth/callback")
def oauth_callback(
    provider: str,
    code: str,
    state: str,
    ctx: RequestContext = Depends(request_context),
) -> RedirectResponse:
    """Complete the OAuth flow, then bounce back to the settings screen.

    Verifies the CSRF ``state`` and exchanges the code server-side; the token
    exchange error string is scrubbed (never surfaced/logged verbatim).
    """
    try:
        with BillingSession().begin(ctx) as s:
            oauth.callback(s, ctx, provider=provider, code=code, state=state)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    origin = load_auth_settings().frontend_origin or ""
    target = f"{origin}/settings/providers?connected={provider}" if origin else "/"
    return RedirectResponse(url=target, status_code=302)
