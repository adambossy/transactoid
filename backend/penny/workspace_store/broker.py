"""The capability broker: create and resolve opaque workspace prefixes.

Tokens are ``secrets.token_urlsafe`` values, never derived from tenant ids, so
an R2 key can only be reached via an RLS-gated Postgres lookup here.
:func:`resolve_readable_prefixes` is the *pre-R2* visibility gate — a joint
session is handed the shared prefix only, so a spouse's private bytes never
reach the temp dir. (RLS would hide them anyway; this makes the guarantee
explicit at the resolution step, per the spec.)
"""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import uuid

from sqlalchemy.orm import Session

from penny.adapters.db.models import WorkspaceHead, WorkspacePrefix
from penny.tenancy.context import RequestContext, SessionMode


@dataclass(frozen=True, slots=True)
class PrefixInfo:
    prefix_token: str
    visibility: str
    owner_user_id: uuid.UUID


def _create(
    session: Session, ctx: RequestContext, *, kind: str, visibility: str
) -> None:
    token = secrets.token_urlsafe(24)
    session.add(
        WorkspacePrefix(
            prefix_token=token,
            household_id=ctx.household_id,
            owner_user_id=ctx.user_id,
            visibility=visibility,
            kind=kind,
        )
    )
    # Flush the prefix before the head so the head's prefix_token FK is
    # satisfiable when SQLite enforces foreign keys.
    session.flush()
    session.add(
        WorkspaceHead(
            prefix_token=token,
            head_manifest_id=None,
            household_id=ctx.household_id,
            owner_user_id=ctx.user_id,
            visibility=visibility,
        )
    )
    session.flush()


def ensure_prefixes(session: Session, ctx: RequestContext) -> None:
    """Idempotently create the prefixes ``ctx`` writes to.

    The household's shared prefix always; the user's private prefix in
    individual mode (a joint session writes shared only, so it needs no private
    prefix). Safe to call on every run — existing prefixes are left untouched.
    """
    shared = (
        session.query(WorkspacePrefix)
        .filter(
            WorkspacePrefix.household_id == ctx.household_id,
            WorkspacePrefix.kind == "shared",
        )
        .one_or_none()
    )
    if shared is None:
        _create(session, ctx, kind="shared", visibility="shared")
    if ctx.session_mode is SessionMode.INDIVIDUAL:
        private = (
            session.query(WorkspacePrefix)
            .filter(
                WorkspacePrefix.owner_user_id == ctx.user_id,
                WorkspacePrefix.kind == "private",
            )
            .one_or_none()
        )
        if private is None:
            _create(session, ctx, kind="private", visibility="private")


def resolve_readable_prefixes(
    session: Session, ctx: RequestContext
) -> list[PrefixInfo]:
    """The prefixes ``ctx`` may read, shared first so private overlays it.

    Individual: ``[shared(household), private(ctx.user)]``. Joint: shared only
    — private rows are never queried (belt-and-suspenders to RLS).
    """
    rows = list(
        session.query(WorkspacePrefix).filter(
            WorkspacePrefix.household_id == ctx.household_id,
            WorkspacePrefix.kind == "shared",
        )
    )
    if ctx.session_mode is SessionMode.INDIVIDUAL:
        rows += list(
            session.query(WorkspacePrefix).filter(
                WorkspacePrefix.owner_user_id == ctx.user_id,
                WorkspacePrefix.kind == "private",
            )
        )
    # Shared first, private second: materialize overlays private onto shared on
    # a path collision, so a user's private edit wins in their own session.
    rows.sort(key=lambda r: 0 if r.kind == "shared" else 1)
    return [PrefixInfo(r.prefix_token, r.visibility, r.owner_user_id) for r in rows]
