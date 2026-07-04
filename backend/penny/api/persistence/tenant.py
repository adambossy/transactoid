"""Owner-scoped web session for personal app state (reminders, onboarding).

These tables are private to a single ``owner_user_id`` within a household
(decision D3): a spouse never sees the other's onboarding items or queued
reminders, and onboarding only ever runs in individual conversations. So — like
``penny.billing.session`` — this binds ``app.current_user`` to the **real** user
id (never the joint nil sentinel), and additionally binds
``app.current_household`` because the RLS predicate keys on both GUCs
(migrations 022/023). No-op GUC on SQLite (no RLS there); the stores additionally
filter every query by ``household_id`` + ``owner_user_id``, the only tenant layer
in SQLite dev.

Distinct from ``BillingSession`` (which binds only ``app.current_user`` for its
household-agnostic owner-private policy) and from ``ConversationStore`` (which
binds the *effective* user so joint threads read shared rows). Reused by both the
reminder queue and the onboarding store so the binding lives in one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from penny.tenancy.context import RequestContext

from .engine import get_web_session_factory


@contextmanager
def owner_web_session(
    ctx: RequestContext, *, session_factory: sessionmaker[Session] | None = None
) -> Iterator[Session]:
    """A transactional web session scoped to ``ctx``'s household + real user.

    Commits on success, rolls back on error. On Postgres it binds the tenant
    GUCs so the ``tenant_isolation`` RLS policies apply; on SQLite it is a plain
    session (the stores' explicit filters are the tenant layer).
    """
    factory = session_factory or get_web_session_factory()
    session = factory()
    try:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT set_config('app.current_household', :h, true), "
                    "set_config('app.current_user', :u, true)"
                ),
                {"h": str(ctx.household_id), "u": str(ctx.user_id)},
            )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
