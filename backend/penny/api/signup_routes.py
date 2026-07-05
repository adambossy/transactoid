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

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from penny.adapters.clerk import ClerkInvites
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


@lru_cache(maxsize=1)
def get_clerk_invites() -> ClerkInvites:
    """The invite provider. Overridden in tests via ``app.dependency_overrides``."""
    return ClerkInvites()


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
