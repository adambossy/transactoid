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
from penny.db import get_db
from penny.signup import InviteError, create_invite
from penny.tenancy.context import RequestContext

from .auth import request_context

router = APIRouter()


@lru_cache(maxsize=1)
def get_clerk_invites() -> ClerkInvites:
    """The invite provider. Overridden in tests via ``app.dependency_overrides``."""
    return ClerkInvites()


class InviteBody(BaseModel):
    email: str = Field(min_length=3)


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
