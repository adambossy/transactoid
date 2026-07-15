"""``ConversationStore`` — CRUD over the website-owned conversation tables.

Self-contained SQLAlchemy over the website store's *own* engine/session
(``engine.py``). It imports neither the finance ``DB`` facade nor any agent
module — that isolation is what the segregation guardrail test enforces.

Every access is tenant-scoped: a conversation belongs to one household and one
owner, and its ``session_mode`` decides visibility (``individual`` → owner-only,
``joint`` → household-shared). The store filters every read/write with that
predicate (app-layer, the only tenant layer on SQLite dev); on Postgres the
session also emits the phase-1a ``SET LOCAL`` GUCs so the ``tenant_isolation``
RLS policy (migration 019) binds on the web-DB connection too. ``owner_user_id``
and ``household_id`` are stamped from the ``RequestContext`` on creation and are
immutable — never taken from the client.

Conventions mirror the finance facade: a ``session()`` context manager that
commits on success and rolls back on error, and ``expunge`` before returning
ORM rows so callers can read them after the session closes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from penny.tenancy.context import RequestContext

from .engine import get_web_session_factory
from .models import Conversation, ConversationMessage, WebBase

# Title is derived from the first user message, truncated to this many chars.
_TITLE_MAX_LEN = 80

# The only valid session modes; ``session_mode`` is immutable after creation.
_VALID_MODES = ("individual", "joint")


class ConversationAccessError(Exception):
    """Conversation exists but is not visible to this principal (route → 404)."""


def _can_access(conv: Conversation, ctx: RequestContext) -> bool:
    """Visibility predicate: same household, and owner-match or joint thread."""
    return conv.household_id == ctx.household_id and (
        conv.owner_user_id == ctx.user_id or conv.session_mode == "joint"
    )


class ConversationStore:
    """Persistence façade for conversations and their messages."""

    def __init__(self, session_factory: Any = None) -> None:
        # Default to the process-wide website engine; tests may inject one.
        self._session_factory = session_factory or get_web_session_factory()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            self._apply_rls_settings(session)
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _apply_rls_settings(self, session: Session) -> None:
        """Bind the phase-1a tenant GUCs on Postgres so web-schema RLS applies.

        Mirrors ``penny.adapters.db.facade.DB._apply_rls_settings``: joint mode
        resolves ``app.current_user`` to the nil sentinel, so RLS returns
        shared-only. No-op on SQLite (no RLS there) and when no context is set.
        """
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        from penny.tenancy.context import effective_user_id, get_request_context

        ctx = get_request_context()
        if ctx is None:
            return
        session.execute(
            text(
                "SELECT set_config('app.current_household', :h, true), "
                "set_config('app.current_user', :u, true)"
            ),
            {"h": str(ctx.household_id), "u": str(effective_user_id(ctx))},
        )

    def create_schema(self) -> None:
        """Build the website store's tables from the models. SQLite ONLY.

        Mirrors ``engine.create_web_schema`` but honors an injected session
        factory's bind so tests can point it at a throwaway engine. On Postgres
        the web.* schema is alembic-owned (migration 019); ``create_all`` is
        refused there.
        """
        bind = self._session_factory.kw.get("bind")
        if bind is None:  # pragma: no cover - default factory always has a bind
            from .engine import create_web_schema

            create_web_schema()
            return
        if bind.dialect.name != "sqlite":
            raise RuntimeError(
                "create_schema()/create_all is SQLite-only; on Postgres the "
                "web.* tables are alembic-owned. Run `penny migrate`."
            )
        WebBase.metadata.create_all(bind)

    # ----- conversations ---------------------------------------------------

    def ensure_conversation(
        self,
        conversation_id: str,
        ctx: RequestContext,
        *,
        session_mode: str = "individual",
    ) -> Conversation:
        """Return the conversation, creating it (tenant-stamped) if absent.

        On create, ``household_id``/``owner_user_id`` come from ``ctx`` and
        ``session_mode`` is fixed for the thread's life. On an existing row the
        client-supplied ``session_mode`` is **ignored** (immutable) and access
        is verified (else ``ConversationAccessError``).
        """
        if session_mode not in _VALID_MODES:
            raise ValueError(
                f"session_mode must be one of {_VALID_MODES}, got {session_mode!r}"
            )
        with self.session() as session:
            existing = session.get(Conversation, conversation_id)
            if existing is not None:
                if not _can_access(existing, ctx):
                    raise ConversationAccessError(conversation_id)
                session.expunge(existing)
                return existing
            conv = Conversation(
                conversation_id=conversation_id,
                household_id=ctx.household_id,
                owner_user_id=ctx.user_id,
                session_mode=session_mode,
            )
            session.add(conv)
            session.flush()
            session.expunge(conv)
            return conv

    def list_conversations(self, ctx: RequestContext) -> list[Conversation]:
        """Return the principal's visible conversations, newest-first.

        Visibility mirrors ``_can_access`` but as a SQL predicate: same
        household, and either owner-owned or a ``joint`` (household-shared)
        thread. Ordered by ``updated_at`` descending so the most recently active
        conversation leads the list. Rows are expunged so callers can read them
        after the session closes.
        """
        with self.session() as session:
            rows = (
                session.query(Conversation)
                .filter(
                    Conversation.household_id == ctx.household_id,
                    or_(
                        Conversation.owner_user_id == ctx.user_id,
                        Conversation.session_mode == "joint",
                    ),
                )
                .order_by(Conversation.updated_at.desc())
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def get_conversation(
        self, conversation_id: str, ctx: RequestContext
    ) -> Conversation:
        """Return the conversation if the principal may see it, else raise.

        A missing row and an inaccessible row both raise
        ``ConversationAccessError`` so a 404 cannot reveal existence.
        """
        with self.session() as session:
            conv = self._require_access(session, conversation_id, ctx)
            session.expunge(conv)
            return conv

    def set_title(self, conversation_id: str, title: str) -> None:
        """Set the conversation title (overwrites any existing title)."""
        with self.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.title = title
                conversation.updated_at = datetime.now()

    def set_title_if_unset(self, conversation_id: str, raw: str) -> None:
        """Derive + set a title from ``raw`` (first user text) only if unset.

        No-op when the conversation already has a title, so the first user
        message wins and later turns don't churn it.
        """
        title = _derive_title(raw)
        if not title:
            return
        with self.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None and not conversation.title:
                conversation.title = title
                conversation.updated_at = datetime.now()

    # ----- messages --------------------------------------------------------

    def _next_seq(self, session: Session, conversation_id: str) -> int:
        """Allocate the next ``seq`` for a conversation under the session.

        ``COALESCE(MAX(seq), -1) + 1`` so the first message is seq 0.
        """
        stmt = select(func.coalesce(func.max(ConversationMessage.seq), -1) + 1).where(
            ConversationMessage.conversation_id == conversation_id
        )
        return int(session.execute(stmt).scalar_one())

    def append_user_message(
        self,
        conversation_id: str,
        ctx: RequestContext,
        *,
        ai_sdk_message_id: str | None,
        text: str,
    ) -> int:
        """Persist a user turn; return its allocated ``seq``.

        User turns are always ``complete`` (no streaming). The ``parts`` array
        mirrors what the bridge / hydration expects for user text. The sender
        is stamped from the real ``ctx.user_id`` — not ``effective_user_id``,
        which collapses to the nil sentinel in joint sessions, exactly where
        attribution matters.
        """
        with self.session() as session:
            self._require_access(session, conversation_id, ctx)
            seq = self._next_seq(session, conversation_id)
            session.add(
                ConversationMessage(
                    conversation_id=conversation_id,
                    ai_sdk_message_id=ai_sdk_message_id,
                    seq=seq,
                    role="user",
                    sender_user_id=ctx.user_id,
                    parts=[{"type": "text", "text": text}],
                    status="complete",
                )
            )
            self._touch_conversation(session, conversation_id)
            return seq

    def upsert_assistant_message(
        self,
        conversation_id: str,
        ctx: RequestContext,
        *,
        ai_sdk_message_id: str | None,
        parts: list[dict[str, Any]],
        status: str,
    ) -> int:
        """Insert or update an assistant turn, keyed by ``ai_sdk_message_id``.

        Idempotent: the same ``(conversation_id, ai_sdk_message_id)`` reconciles
        the existing row in place (e.g. the ``streaming`` placeholder is
        finalized to ``complete`` on RunEnd) rather than duplicating. Returns
        the row's ``seq``.
        """
        with self.session() as session:
            self._require_access(session, conversation_id, ctx)
            existing = self._find_by_ai_sdk_id(
                session, conversation_id, ai_sdk_message_id
            )
            if existing is not None:
                existing.parts = parts
                existing.status = status
                existing.updated_at = datetime.now()
                seq = existing.seq
            else:
                seq = self._next_seq(session, conversation_id)
                session.add(
                    ConversationMessage(
                        conversation_id=conversation_id,
                        ai_sdk_message_id=ai_sdk_message_id,
                        seq=seq,
                        role="assistant",
                        parts=parts,
                        status=status,
                    )
                )
            self._touch_conversation(session, conversation_id)
            return seq

    def get_conversation_messages(
        self, conversation_id: str, ctx: RequestContext
    ) -> list[ConversationMessage]:
        """Return all messages for an accessible conversation, ordered by seq.

        Raises ``ConversationAccessError`` if the principal cannot see the
        conversation (or it does not exist).
        """
        with self.session() as session:
            self._require_access(session, conversation_id, ctx)
            rows = (
                session.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.seq.asc())
                .all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def latest_activity(self, conversation_id: str) -> tuple[str, datetime] | None:
        """The (role, updated_at) of a conversation's newest message — unscoped.

        A system read for the sandbox reaper (no per-conversation principal): the
        persisted transcript is the reaper's durable idle clock. A trailing
        ``user`` message means a turn is in flight (persisted up front, before
        dispatch); an ``assistant`` message means the turn finished. ``None`` when
        the conversation has no messages yet.
        """
        with self.session() as session:
            row = (
                session.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.seq.desc())
                .first()
            )
            return None if row is None else (row.role, row.updated_at)

    # ----- internals -------------------------------------------------------

    def _require_access(
        self, session: Session, conversation_id: str, ctx: RequestContext
    ) -> Conversation:
        """Load the conversation and assert the principal may access it.

        A missing row and an inaccessible row both raise
        ``ConversationAccessError`` (so the route's 404 hides existence).
        """
        conv = session.get(Conversation, conversation_id)
        if conv is None or not _can_access(conv, ctx):
            raise ConversationAccessError(conversation_id)
        return conv

    def _find_by_ai_sdk_id(
        self,
        session: Session,
        conversation_id: str,
        ai_sdk_message_id: str | None,
    ) -> ConversationMessage | None:
        if ai_sdk_message_id is None:
            return None
        return (
            session.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.ai_sdk_message_id == ai_sdk_message_id,
            )
            .first()
        )

    def _touch_conversation(self, session: Session, conversation_id: str) -> None:
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = datetime.now()


def _derive_title(raw: str) -> str:
    """Collapse whitespace and truncate the first user message into a title."""
    collapsed = " ".join(raw.split())
    if len(collapsed) <= _TITLE_MAX_LEN:
        return collapsed
    return collapsed[: _TITLE_MAX_LEN - 1].rstrip() + "…"
