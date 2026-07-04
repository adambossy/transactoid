"""Account provisioning + invites — the website-domain signup service.

Owns "provision-or-join": phase-2's auth dependency calls
``resolve_or_provision_identity`` in its unknown-user branch, and the website's
invite routes call ``create_invite`` / ``list_pending_invites`` /
``revoke_invite``. The invariant is **one individual = one household**: a solo
signup gets a fresh isolated household; an invite is a *pending* ``users`` row
(``external_auth_id IS NULL``) in the inviter's household that a first login
atomically claims (phase-2 linking). ``household_id`` is always taken from the
caller's ``RequestContext`` — never from a request body.

This module is invoked only by website code (the auth dependency and the API
routes); no agent tool or skill imports it, so the website→agent one-directional
boundary holds.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from penny.adapters.db.models import Household, User
from penny.bootstrap import seed_taxonomy_for_household


def provision_solo_household(
    session: Session, *, email: str, external_auth_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an isolated solo household + its user + seeded taxonomy.

    Idempotent: if a user with this (lowercased) email already exists, returns
    its ``(household_id, user_id)`` without creating anything. The
    ``users.email`` UNIQUE constraint is the backstop under a signup race.
    """
    normalized = email.strip().lower()
    existing = session.query(User).filter(User.email == normalized).one_or_none()
    if existing is not None:
        return existing.household_id, existing.user_id
    local = normalized.split("@", 1)[0]
    hh = Household(name=f"{local}'s household")
    session.add(hh)
    session.flush()
    user = User(
        household_id=hh.household_id,
        email=normalized,
        external_auth_id=external_auth_id,
    )
    session.add(user)
    session.flush()
    seed_taxonomy_for_household(session, hh.household_id)
    return hh.household_id, user.user_id


def resolve_or_provision_identity(
    session: Session, *, email: str, external_auth_id: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Resolve a verified identity to ``(household_id, user_id)``, provisioning
    a solo household on first sight of an un-invited user.

    Precedence:
      1. existing user by ``external_auth_id`` (survives email changes);
      2. a **pending** invite row by email (``external_auth_id IS NULL``) → claim
         it (stamp ``external_auth_id``) and join that household;
      3. otherwise auto-provision a fresh solo household.
    """
    normalized = email.strip().lower()
    by_sub = (
        session.query(User)
        .filter(User.external_auth_id == external_auth_id)
        .one_or_none()
    )
    if by_sub is not None:
        return by_sub.household_id, by_sub.user_id
    # Claim a pending invite atomically (phase-2 first-login linking).
    claimed = (
        session.query(User)
        .filter(User.email == normalized, User.external_auth_id.is_(None))
        .one_or_none()
    )
    if claimed is not None:
        claimed.external_auth_id = external_auth_id
        session.flush()
        return claimed.household_id, claimed.user_id
    return provision_solo_household(
        session, email=normalized, external_auth_id=external_auth_id
    )
