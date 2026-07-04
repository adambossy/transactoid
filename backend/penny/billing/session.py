"""Web-session helper for the billing tables — owner-scoped, real-user GUC.

The billing tables reuse the website store's engine (``penny.api.persistence``)
but bind the tenant GUC **differently** from the conversation store: billing
data is owner-private to the *real* user even in a joint session, so this sets
``app.current_user`` to ``ctx.user_id`` directly (never the joint nil sentinel
that the conversation store uses for household-shared visibility). The billing
RLS policy (migrations 020/021) keys on that GUC.

No-op GUC on SQLite (no RLS there); the vault/metering stores additionally
filter every query by ``user_id`` so SQLite dev is still tenant-isolated.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from penny.api.persistence.engine import get_web_session_factory
from penny.tenancy.context import RequestContext


class BillingSession:
    """Owns the web session factory + owner-scoped RLS binding for billing."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or get_web_session_factory()

    @contextmanager
    def begin(self, ctx: RequestContext) -> Iterator[Session]:
        """A transactional session with ``app.current_user`` bound to the real
        user, committing on success and rolling back on error."""
        session = self._session_factory()
        try:
            self._bind_owner(session, ctx)
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _bind_owner(self, session: Session, ctx: RequestContext) -> None:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        session.execute(
            text("SELECT set_config('app.current_user', :u, true)"),
            {"u": str(ctx.user_id)},
        )
