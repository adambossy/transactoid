"""Sanctioned subscription OAuth — Authorization-Code + PKCE, server-side.

For providers where we register our **own** OAuth client (not CLI
impersonation): PKCE (S256), an **independent CSRF-safe ``state``** bound to the
user server-side, and a registered HTTPS redirect on our domain. Token exchange
stores ``{access, refresh, expires}`` encrypted via the vault (``kind='oauth'``);
refresh rotates the refresh token **atomically under the per-(user,provider) row
lock** and runs proactively before expiry.

**Claude Pro/Max is explicitly excluded** (see the spec Decisions): its flow
requires impersonating the Claude Code CLI, which Anthropic disputes for hosted
third-party use. Only providers with a real registered client are configured.

Provider config comes from the ``PENNY_*`` env seam (per provider):
``PENNY_OAUTH_<PROVIDER>_CLIENT_ID`` / ``_CLIENT_SECRET`` / ``_AUTHORIZE_URL`` /
``_TOKEN_URL`` / ``_REDIRECT_URI`` / ``_SCOPES``.

The pending ``state → {user, provider, code_verifier}`` map is a process-local
server-side store with a TTL. A multi-process deployment needs a shared store
(Redis/DB); that is a documented follow-up (only relevant once a provider is
actually registered — none is in v1).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import secrets
import time
from typing import Any, Protocol
import urllib.parse
import urllib.request

from sqlalchemy.orm import Session

from penny.tenancy.context import RequestContext

from . import vault

# state entries older than this are rejected (CSRF replay / abandoned flows).
_STATE_TTL_SECONDS = 600
# Refresh this many seconds before the stored expiry (proactive skew).
_REFRESH_SKEW_SECONDS = 300


class OAuthError(Exception):
    """OAuth flow failure (bad state, unconfigured provider, exchange error)."""


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    redirect_uri: str
    scopes: str


def oauth_config(provider: str) -> OAuthConfig:
    """Load a provider's OAuth client config from ``PENNY_OAUTH_<PROVIDER>_*``.

    Raises ``OAuthError`` if the provider has no registered client — we never
    ship a CLI-impersonation fallback.
    """
    p = provider.upper()

    def _env(suffix: str) -> str:
        return os.environ.get(f"PENNY_OAUTH_{p}_{suffix}", "").strip()

    client_id = _env("CLIENT_ID")
    if not client_id:
        raise OAuthError(f"provider {provider!r} has no registered OAuth client")
    return OAuthConfig(
        client_id=client_id,
        client_secret=_env("CLIENT_SECRET"),
        authorize_url=_env("AUTHORIZE_URL"),
        token_url=_env("TOKEN_URL"),
        redirect_uri=_env("REDIRECT_URI"),
        scopes=_env("SCOPES"),
    )


class TokenExchanger(Protocol):
    """Exchange an authorization code / refresh token for a token set.

    Injected so tests fake the provider; the default POSTs to the token URL.
    Returns ``{access_token, refresh_token?, expires_in?}``.
    """

    def __call__(self, config: OAuthConfig, form: dict[str, str]) -> dict[str, Any]: ...


def _http_token_exchange(config: OAuthConfig, form: dict[str, str]) -> dict[str, Any]:
    """Default token exchange: POST url-encoded form to the token endpoint."""
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(  # noqa: S310 - token_url is our configured HTTPS endpoint
        config.token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except Exception as exc:  # scrub — never log the form (it carries secrets)
        raise OAuthError("token exchange failed") from exc


# --- PKCE + CSRF state -------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class _PendingState:
    user_id: str
    provider: str
    code_verifier: str
    created_at: float


# Process-local pending-state store (server-side). See module docstring.
_PENDING: dict[str, _PendingState] = {}


def _put_state(ctx: RequestContext, provider: str, code_verifier: str) -> str:
    state = secrets.token_urlsafe(32)
    _PENDING[state] = _PendingState(
        user_id=str(ctx.user_id),
        provider=provider,
        code_verifier=code_verifier,
        created_at=time.time(),
    )
    return state


def _take_state(state: str, ctx: RequestContext, provider: str) -> _PendingState:
    entry = _PENDING.pop(state, None)
    if entry is None:
        raise OAuthError("unknown or already-used OAuth state")
    if time.time() - entry.created_at > _STATE_TTL_SECONDS:
        raise OAuthError("OAuth state expired")
    if entry.user_id != str(ctx.user_id) or entry.provider != provider:
        raise OAuthError("OAuth state does not match the session")
    return entry


# --- Public flow -------------------------------------------------------------


def start(session: Session, ctx: RequestContext, *, provider: str) -> dict[str, str]:
    """Begin the flow: return ``{authorize_url}`` with PKCE + a bound state.

    ``session`` is unused here (kept for a symmetric signature / future
    persistence of state); the pending state is held server-side.
    """
    del session
    config = oauth_config(provider)
    verifier, challenge = _pkce_pair()
    state = _put_state(ctx, provider, verifier)
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {"authorize_url": f"{config.authorize_url}?{urllib.parse.urlencode(params)}"}


def callback(
    session: Session,
    ctx: RequestContext,
    *,
    provider: str,
    code: str,
    state: str,
    exchanger: TokenExchanger = _http_token_exchange,
) -> None:
    """Complete the flow: verify ``state``, exchange ``code``, store encrypted.

    The CSRF ``state`` is verified (and consumed) before any exchange; a
    mismatch raises before we touch the provider. On success the token set is
    stored via the vault under the per-(user,provider) row lock.
    """
    entry = _take_state(state, ctx, provider)
    config = oauth_config(provider)
    tokens = exchanger(
        config,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code_verifier": entry.code_verifier,
        },
    )
    _store_tokens(session, ctx, provider, tokens)


def refresh(
    session: Session,
    ctx: RequestContext,
    *,
    provider: str,
    exchanger: TokenExchanger = _http_token_exchange,
    now: float | None = None,
) -> bool:
    """Proactively refresh the OAuth token if within the skew of expiry.

    Rotates the refresh token and persists the new set **atomically under the
    vault's per-(user,provider) row lock** (a lost write → ``invalid_grant``).
    Returns whether a refresh was performed. No-op if the credential is missing,
    not OAuth, has no refresh token, or is not yet near expiry.
    """
    cred = vault.get_credential(session, ctx, provider=provider)
    from agent_harness.core.credentials import OAuthCredential

    if not isinstance(cred, OAuthCredential) or not cred.refresh_token:
        return False
    clock = time.time() if now is None else now
    if cred.expires_at is not None and clock < cred.expires_at - _REFRESH_SKEW_SECONDS:
        return False  # still fresh enough
    config = oauth_config(provider)
    tokens = exchanger(
        config,
        {
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
    )
    _store_tokens(session, ctx, provider, tokens, fallback_refresh=cred.refresh_token)
    return True


def _store_tokens(
    session: Session,
    ctx: RequestContext,
    provider: str,
    tokens: dict[str, Any],
    *,
    fallback_refresh: str | None = None,
) -> None:
    access = tokens.get("access_token")
    if not access:
        raise OAuthError("token exchange returned no access_token")
    expires_in = tokens.get("expires_in")
    expires_at = (
        datetime.now().timestamp() + float(expires_in)
        if expires_in is not None
        else None
    )
    vault.upsert_oauth(
        session,
        ctx,
        provider=provider,
        access_token=access,
        # Some providers omit refresh_token on refresh — keep the prior one.
        refresh_token=tokens.get("refresh_token") or fallback_refresh,
        expires_at=expires_at,
    )
