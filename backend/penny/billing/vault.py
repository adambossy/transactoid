"""Encrypted per-user provider-credential vault.

Stores a BYO provider **API key** or **OAuth token** per ``(user_id, provider)``,
encrypted at rest (versioned envelope, ``penny.security.token_cipher``). Reads
for display expose only a masked hint; the plaintext is returned only by
``get_credential`` at the outbound-LLM call site (the gate), never to the client.

Every function takes an already-RLS-bound web ``Session`` (see
``penny.billing.session.BillingSession``) and the ``RequestContext``. Writes are
serialized under a per-``(user, provider)`` row lock (``with_for_update`` on
Postgres) so a concurrent upsert / OAuth-refresh rotation can't lose a write.
On SQLite dev every query also filters by ``user_id`` (the only tenant layer).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_harness.core.credentials import (
    ApiKeyCredential,
    Credential,
    OAuthCredential,
)
from sqlalchemy.orm import Session

from penny.security.token_cipher import decrypt_secret, encrypt_secret
from penny.tenancy.context import RequestContext

from .models import UserCredential


def _mask(key: str) -> str:
    """A non-secret display hint: ``sk-…1234`` (last 4), or ``…`` if too short."""
    tail = key[-4:] if len(key) >= 4 else ""
    return f"sk-…{tail}" if tail else "…"


def _locked_row(
    session: Session, ctx: RequestContext, provider: str
) -> UserCredential | None:
    """Load the ``(user, provider)`` row under a write lock (no-op on SQLite)."""
    return (
        session.query(UserCredential)
        .filter(
            UserCredential.user_id == ctx.user_id,
            UserCredential.provider == provider,
        )
        .with_for_update()
        .first()
    )


def upsert_api_key(
    session: Session, ctx: RequestContext, *, provider: str, key: str
) -> None:
    """Encrypt and store (or replace) the user's API key for ``provider``.

    Idempotent per ``(user, provider)``: an existing row is updated in place
    under the row lock. ``meta`` carries only the masked hint — never the key.
    """
    ciphertext = encrypt_secret(key)
    hint = _mask(key)
    row = _locked_row(session, ctx, provider)
    if row is not None:
        row.kind = "api_key"
        row.secret_ciphertext = ciphertext
        row.meta = {"hint": hint}
        row.updated_at = datetime.now()
        return
    session.add(
        UserCredential(
            user_id=ctx.user_id,
            provider=provider,
            kind="api_key",
            secret_ciphertext=ciphertext,
            meta={"hint": hint},
        )
    )


def upsert_oauth(
    session: Session,
    ctx: RequestContext,
    *,
    provider: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: float | None,
) -> None:
    """Encrypt and store (or rotate) the user's OAuth tokens for ``provider``.

    The access + refresh tokens are stored as one JSON secret so a refresh
    rotation persists both atomically under the row lock. ``meta`` records only
    the non-secret expiry.
    """
    import json

    ciphertext = encrypt_secret(
        json.dumps({"access_token": access_token, "refresh_token": refresh_token})
    )
    meta: dict[str, Any] = {"expires_at": expires_at}
    row = _locked_row(session, ctx, provider)
    if row is not None:
        row.kind = "oauth"
        row.secret_ciphertext = ciphertext
        row.meta = meta
        row.updated_at = datetime.now()
        return
    session.add(
        UserCredential(
            user_id=ctx.user_id,
            provider=provider,
            kind="oauth",
            secret_ciphertext=ciphertext,
            meta=meta,
        )
    )


def get_credential(
    session: Session, ctx: RequestContext, *, provider: str
) -> Credential | None:
    """Decrypt and return the user's credential for ``provider`` (or ``None``).

    Backend-only: the plaintext key/token never leaves this process. Returns a
    harness ``ApiKeyCredential`` / ``OAuthCredential`` the model client is built
    from.
    """
    row = (
        session.query(UserCredential)
        .filter(
            UserCredential.user_id == ctx.user_id,
            UserCredential.provider == provider,
        )
        .first()
    )
    if row is None:
        return None
    plaintext = decrypt_secret(row.secret_ciphertext)
    if row.kind == "oauth":
        import json

        data = json.loads(plaintext)
        expires_at = (row.meta or {}).get("expires_at")
        return OAuthCredential(
            provider=provider,
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
        )
    return ApiKeyCredential(provider=provider, key=plaintext)


def masked(session: Session, ctx: RequestContext) -> list[dict[str, Any]]:
    """Every credential the user has, as non-secret display rows.

    Returns ``[{provider, kind, hint, updated_at}, ...]`` — never the secret.
    """
    rows = (
        session.query(UserCredential)
        .filter(UserCredential.user_id == ctx.user_id)
        .order_by(UserCredential.provider.asc())
        .all()
    )
    return [
        {
            "provider": row.provider,
            "kind": row.kind,
            "hint": (row.meta or {}).get("hint"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


def remove(session: Session, ctx: RequestContext, *, provider: str) -> None:
    """Delete the user's credential for ``provider`` (idempotent no-op if absent)."""
    row = _locked_row(session, ctx, provider)
    if row is not None:
        session.delete(row)
