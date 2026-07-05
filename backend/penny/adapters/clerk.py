"""Thin adapter over Clerk's Invitations REST API.

Implements the ``penny.signup.ClerkInvites`` seam so the signup service stays
free of Clerk specifics. ``FakeClerkInvites`` stands in for this in tests; the
real ``ClerkInvites`` here is what production wires in. It authenticates with the
phase-2 ``CLERK_SECRET_KEY`` and speaks the documented endpoints:

- create:  ``POST /v1/invitations`` ``{"email_address": ...}``
- revoke:  ``POST /v1/invitations/{id}/revoke`` (id resolved from the email via
  ``GET /v1/invitations?status=pending``)

Uses ``urllib`` (no new dependency), matching ``penny.billing.oauth``. Operations
are shaped to be idempotent: re-creating a duplicate invitation and revoking an
absent one are both no-ops, so the signup service can retry safely.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

_API_BASE = "https://api.clerk.com/v1"
_TIMEOUT = 30
# api.clerk.com sits behind Cloudflare, which bans the default `Python-urllib`
# User-Agent with error 1010. A named UA gets us through.
_USER_AGENT = "Penny-backend/1.0 (+https://github.com/adambossy/transactoid)"


class ClerkError(RuntimeError):
    """A Clerk Invitations API call failed (network or non-2xx, non-idempotent)."""


class ClerkInvites:
    """Production ``ClerkInvites`` implementation backed by the Clerk REST API."""

    def __init__(self, secret_key: str | None = None) -> None:
        # Read lazily-defaulted so importing this module never requires the key;
        # only *using* it against real Clerk does.
        self._secret_key = secret_key or os.environ.get("CLERK_SECRET_KEY", "").strip()

    def _require_key(self) -> str:
        if not self._secret_key:
            raise ClerkError("CLERK_SECRET_KEY is not set")
        return self._secret_key

    def _request(
        self, method: str, path: str, *, body: dict | None = None
    ) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 - fixed HTTPS Clerk endpoint
            f"{_API_BASE}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._require_key()}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                parsed = json.loads(payload or b"null")
            except json.JSONDecodeError:
                parsed = None
            return exc.code, parsed

    def create_invitation(self, email: str) -> None:
        status, payload = self._request(
            "POST", "/invitations", body={"email_address": email}
        )
        if status < 300:
            return
        # Idempotent: an already-outstanding invitation for this email is fine.
        if status in (400, 422) and _is_duplicate(payload):
            return
        raise ClerkError(f"create_invitation failed ({status})")

    def revoke_invitation(self, email: str) -> None:
        invitation_id = self._find_pending_id(email)
        if invitation_id is None:
            return  # already revoked / never issued — no-op
        status, _ = self._request("POST", f"/invitations/{invitation_id}/revoke")
        if status >= 300:
            raise ClerkError(f"revoke_invitation failed ({status})")

    def _find_pending_id(self, email: str) -> str | None:
        query = urllib.parse.urlencode({"status": "pending"})
        status, payload = self._request("GET", f"/invitations?{query}")
        if status >= 300 or not isinstance(payload, list):
            return None
        target = email.strip().lower()
        for inv in payload:
            if (
                isinstance(inv, dict)
                and str(inv.get("email_address", "")).lower() == target
            ):
                got = inv.get("id")
                return str(got) if got else None
        return None


def fetch_user_identity(
    sub: str, *, secret_key: str | None = None
) -> tuple[str | None, bool]:
    """Resolve ``(primary_email, email_verified)`` for a Clerk user via the API.

    Clerk's default session token omits email claims, so the auth dependency
    falls back to this on **first login** (when the subject is not yet linked to
    a ``users`` row). One call per user at link time; returning users resolve by
    ``external_auth_id`` and never reach here. ``GET /v1/users/{id}`` returns the
    user's ``email_addresses`` with per-address ``verification.status`` and the
    ``primary_email_address_id`` selecting the primary one.
    """
    key = (secret_key or os.environ.get("CLERK_SECRET_KEY", "")).strip()
    if not key:
        raise ClerkError("CLERK_SECRET_KEY is not set")
    req = urllib.request.Request(  # noqa: S310 - fixed HTTPS Clerk endpoint
        f"{_API_BASE}/users/{urllib.parse.quote(sub, safe='')}",
        method="GET",
        headers={"Authorization": f"Bearer {key}", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            user = json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read() or b""
        from loguru import logger

        logger.bind(
            sub=sub, status=exc.code, body=body[:400].decode("utf-8", "replace")
        ).error("Clerk fetch_user_identity failed")
        raise ClerkError(
            f"fetch_user_identity failed ({exc.code}): {body[:200].decode('utf-8', 'replace')}"
        ) from None
    if not isinstance(user, dict):
        return None, False
    primary_id = user.get("primary_email_address_id")
    for addr in user.get("email_addresses") or []:
        if isinstance(addr, dict) and addr.get("id") == primary_id:
            email = addr.get("email_address")
            verified = (addr.get("verification") or {}).get("status") == "verified"
            return (str(email) if email else None, bool(verified))
    return None, False


def _is_duplicate(payload: object) -> bool:
    """True when a Clerk error payload signals an already-existing invitation."""
    if not isinstance(payload, dict):
        return False
    for err in payload.get("errors", []) or []:
        if isinstance(err, dict) and "duplicate" in str(err.get("code", "")).lower():
            return True
    return False
