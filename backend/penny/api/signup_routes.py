"""Website API routes for account bootstrap, household, and invites.

The website-domain surface over ``penny.signup``. Every route is authed
(``request_context``) and derives its tenant from ``ctx.household_id`` — the
``household_id`` is never read from a request body, so a caller can only ever act
on their own household. The Clerk invite provider is injected via
``get_clerk_invites`` so tests can override it with a fake.

Mounted on the app by ``penny.api.main`` (mirrors ``billing_routes``), which
keeps the shared ``main.py`` edit to a single ``include_router`` line.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from penny.adapters.clerk import ClerkError, ClerkInvites, fetch_user_profile
from penny.adapters.db.models import Household, User
from penny.db import get_db
from penny.signup import (
    InviteError,
    create_invite,
    list_pending_invites,
    rename_household,
    revoke_invite,
)
from penny.tenancy.context import RequestContext

from .auth import request_context

router = APIRouter()

# Clerk profiles are fetched live (never persisted — the deliberate "no
# syncing" decision) but the members list renders on every drawer open, so a
# short in-process cache bounds Clerk traffic to ~one call per member per TTL.
_PROFILE_TTL_SECONDS = 300.0
_profile_cache: dict[str, tuple[float, dict[str, str | None]]] = {}


@lru_cache(maxsize=1)
def get_clerk_invites() -> ClerkInvites:
    """The invite provider. Overridden in tests via ``app.dependency_overrides``."""
    return ClerkInvites()


@lru_cache(maxsize=1)
def get_profile_fetcher() -> Callable[[str], dict[str, str | None]]:
    """The Clerk profile reader. Overridden in tests via ``dependency_overrides``."""
    return fetch_user_profile


def _cached_profile(
    fetch: Callable[[str], dict[str, str | None]], sub: str
) -> dict[str, str | None]:
    """Fetch a member's Clerk profile through the TTL cache.

    A failed fetch (Clerk down, no secret key in dev) is a normal degraded
    state — return an empty profile so the member renders with initials — and
    is not cached, so the next request retries.
    """
    now = time.monotonic()
    hit = _profile_cache.get(sub)
    if hit is not None and now - hit[0] < _PROFILE_TTL_SECONDS:
        return hit[1]
    try:
        profile = fetch(sub)
    except ClerkError as exc:
        logger.bind(sub=sub).warning(f"member profile fetch failed: {exc}")
        return {"image_url": None, "first_name": None, "last_name": None}
    _profile_cache[sub] = (now, profile)
    return profile


class InviteBody(BaseModel):
    email: str = Field(min_length=3)


class HouseholdPatch(BaseModel):
    name: str = Field(min_length=1)


@router.get("/api/me")
def get_me(
    ctx: RequestContext = Depends(request_context),
) -> dict[str, str]:
    """Bootstrap: the caller's identity + household.

    The auth dependency has already run ``resolve_or_provision_identity``, so by
    the time this route executes the household exists (a first call after signup
    triggers provisioning inside the dependency).
    """
    with get_db().session_for(ctx) as s:
        user = s.query(User).filter(User.user_id == ctx.user_id).one()
        household = (
            s.query(Household).filter(Household.household_id == ctx.household_id).one()
        )
        return {
            "user_id": str(user.user_id),
            "email": user.email,
            "household_id": str(household.household_id),
            "household_name": household.name,
        }


@router.get("/api/household/members")
def get_household_members(
    ctx: RequestContext = Depends(request_context),
    fetch_profile: Callable[[str], dict[str, str | None]] = Depends(
        get_profile_fetcher
    ),
) -> dict[str, list[dict[str, Any]]]:
    """The household's active members with their live Clerk (Google) avatars.

    Members are the household's ``users`` rows with a linked login — pending
    invitees (``external_auth_id`` NULL) have no Clerk account or picture and
    are listed by ``GET /api/invites`` instead. ``image_url`` is fetched from
    Clerk per member (TTL-cached, never persisted) and is null when Clerk has
    no image or is unreachable; the client falls back to initials.
    """
    with get_db().session_for(ctx) as s:
        users = (
            s.query(User)
            .filter(
                User.household_id == ctx.household_id,
                User.external_auth_id.isnot(None),
            )
            # created_at has second resolution, so members provisioned in the
            # same instant need the unique email as a deterministic tiebreak.
            .order_by(User.created_at, User.email)
            .all()
        )
        members = []
        for user in users:
            profile = _cached_profile(fetch_profile, user.external_auth_id)
            members.append(
                {
                    "user_id": str(user.user_id),
                    "email": user.email,
                    # First name when Clerk has one, else the email local-part —
                    # decided server-side so every client names members alike.
                    "display_name": profile["first_name"]
                    or user.email.split("@", 1)[0],
                    "image_url": profile["image_url"],
                    "is_you": user.user_id == ctx.user_id,
                }
            )
    return {"members": members}


@router.patch("/api/household")
def patch_household(
    body: HouseholdPatch,
    ctx: RequestContext = Depends(request_context),
) -> dict[str, str]:
    """Rename the caller's own household."""
    with get_db().session_for(ctx) as s:
        rename_household(s, ctx, name=body.name)
    return {"status": "renamed", "name": body.name}


@router.post("/api/invites", status_code=201)
def post_invite(
    body: InviteBody,
    ctx: RequestContext = Depends(request_context),
    clerk: ClerkInvites = Depends(get_clerk_invites),
) -> dict[str, str]:
    """Invite a new email into the caller's household.

    409 when the email already belongs to an active account (start-fresh case).
    """
    try:
        with get_db().session_for(ctx) as s:
            email = create_invite(s, ctx, email=body.email, clerk=clerk)
    except InviteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "invited", "email": email}


@router.get("/api/invites")
def get_invites(
    ctx: RequestContext = Depends(request_context),
) -> dict[str, list[str]]:
    """List this household's pending (un-claimed) invite emails."""
    with get_db().session_for(ctx) as s:
        return {"invites": list_pending_invites(s, ctx)}


@router.delete("/api/invites/{email}")
def delete_invite(
    email: str,
    ctx: RequestContext = Depends(request_context),
    clerk: ClerkInvites = Depends(get_clerk_invites),
) -> dict[str, str]:
    """Revoke a pending invite in the caller's household (idempotent)."""
    with get_db().session_for(ctx) as s:
        revoke_invite(s, ctx, email=email, clerk=clerk)
    return {"status": "revoked", "email": email.strip().lower()}
