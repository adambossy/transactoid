"""Map a verified Clerk identity to an existing ``users`` row.

Phase 2 does no user creation: identities are *linked* to rows provisioned
earlier. Resolution order is (1) by ``external_auth_id`` (survives email
changes), (2) a first-login link that stamps ``external_auth_id`` onto the row
whose verified email matches — atomic and guarded by ``email_verified`` — and
(3) reject with ``UnknownUserError`` (→ HTTP 403) so an authenticated stranger
gets no access. Phase 4 later replaces branch (3) with auto-provision.
"""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from penny.adapters.db.models import User


class AuthError(Exception):
    """Base for auth failures."""


class UnknownUserError(AuthError):
    """Authenticated identity has no matching users row (maps to HTTP 403)."""


def link_or_resolve_user(
    session: Session, *, sub: str, email: str | None, email_verified: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    by_sub = session.query(User).filter(User.external_auth_id == sub).one_or_none()
    if by_sub is not None:
        return by_sub.household_id, by_sub.user_id
    if email and email_verified:
        normalized = email.strip().lower()
        pending = (
            session.query(User)
            .filter(
                func.lower(User.email) == normalized,
                User.external_auth_id.is_(None),
            )
            .with_for_update()
            .one_or_none()
        )
        if pending is not None:
            pending.external_auth_id = sub  # atomic first-login link
            session.flush()
            logger.bind(user_id=str(pending.user_id)).info(
                "Linked Clerk subject to user on first login"
            )
            return pending.household_id, pending.user_id
    raise UnknownUserError(f"no user for subject {sub!r}")
