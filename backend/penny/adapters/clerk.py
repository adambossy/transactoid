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
import time
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


def _get_user(sub: str, *, secret_key: str | None, op: str) -> dict[str, object]:
    """``GET /v1/users/{id}`` — shared fetch for the identity/profile readers.

    Normalizes a non-dict payload to ``{}`` so callers can ``.get(...)``
    without their own shape guard.
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
        ).error(f"Clerk {op} failed")
        raise ClerkError(
            f"{op} failed ({exc.code}): {body[:200].decode('utf-8', 'replace')}"
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        # URLError/TimeoutError/ConnectionError (all OSError) are the common
        # outage modes — Clerk unreachable rather than answering with an HTTP
        # error — and a garbled body decodes to JSONDecodeError. Translate them
        # all so callers need to know only ClerkError.
        from loguru import logger

        logger.bind(sub=sub, error=repr(exc)).error(f"Clerk {op} failed")
        raise ClerkError(f"{op} failed: {exc!r}") from None
    return user if isinstance(user, dict) else {}


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
    user = _get_user(sub, secret_key=secret_key, op="fetch_user_identity")
    primary_id = user.get("primary_email_address_id")
    for addr in user.get("email_addresses") or []:
        if isinstance(addr, dict) and addr.get("id") == primary_id:
            email = addr.get("email_address")
            verified = (addr.get("verification") or {}).get("status") == "verified"
            return (str(email) if email else None, bool(verified))
    return None, False


# The empty profile: what a member without Clerk data (or with Clerk
# unreachable) resolves to. Callers render initials from it.
EMPTY_PROFILE: dict[str, str | None] = {"image_url": None, "first_name": None}

# Profiles are fetched live (never persisted — the deliberate "no syncing"
# decision) but callers render them often, so a short in-process cache bounds
# Clerk traffic to ~one call per member per TTL. Failures are cached briefly
# too, so a Clerk outage costs one timeout per member per window rather than
# one per request.
_PROFILE_TTL_SECONDS = 300.0
_PROFILE_FAILURE_TTL_SECONDS = 45.0
_profile_cache: dict[str, tuple[float, dict[str, str | None]]] = {}


def fetch_user_profile(
    sub: str, *, secret_key: str | None = None
) -> dict[str, str | None]:
    """Resolve ``{image_url, first_name}`` for a Clerk user, uncached.

    The profile Clerk mirrors from the user's Google account — ``image_url`` is
    the Gmail profile picture (a publicly loadable ``img.clerk.com`` URL, so it
    can be handed straight to the browser). Raises ``ClerkError`` on failure; a
    missing field comes back ``None``.
    """
    user = _get_user(sub, secret_key=secret_key, op="fetch_user_profile")

    def _opt(field: str) -> str | None:
        got = user.get(field)
        return str(got) if got else None

    return {
        "image_url": _opt("image_url"),
        "first_name": _opt("first_name"),
    }


def fetch_cached_user_profile(sub: str) -> dict[str, str | None]:
    """``fetch_user_profile`` through the TTL cache, degradation absorbed.

    A failed fetch (Clerk down, no secret key in dev) is a normal degraded
    state for profile consumers — it resolves to ``EMPTY_PROFILE`` (rendered
    as initials) and is negatively cached for a short window so the next
    request retries soon without every request paying the timeout. Never
    raises.
    """
    now = time.monotonic()
    hit = _profile_cache.get(sub)
    if hit is not None and now < hit[0]:
        return hit[1]
    try:
        profile = fetch_user_profile(sub)
        expires = now + _PROFILE_TTL_SECONDS
    except ClerkError as exc:
        from loguru import logger

        logger.bind(sub=sub).warning(f"profile fetch degraded: {exc}")
        profile = EMPTY_PROFILE
        expires = now + _PROFILE_FAILURE_TTL_SECONDS
    _profile_cache[sub] = (expires, profile)
    return profile


def _is_duplicate(payload: object) -> bool:
    """True when a Clerk error payload signals an already-existing invitation."""
    if not isinstance(payload, dict):
        return False
    for err in payload.get("errors", []) or []:
        if isinstance(err, dict) and "duplicate" in str(err.get("code", "")).lower():
            return True
    return False
