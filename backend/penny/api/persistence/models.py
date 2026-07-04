"""Conversation-persistence ORM models on the website's own ``Base``.

These tables are deliberately **not** registered on the finance
``penny.adapters.db.models.Base``. Keeping them on a separate declarative base
(and a separate engine — see ``engine.py``) is what keeps the agent's
``run_sql`` blast radius scoped to the finance schema.

A message stores its ordered AI SDK ``parts`` as a single JSON array column —
the natural read/write unit is the whole UIMessage, and we never query across
individual parts. See the plan (§1) for the JSON-column rationale.
"""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# Logical schema name for the conversation tables. On Postgres the engine maps
# this to a real ``web`` schema (segregation lever); on SQLite the engine maps
# it to ``None`` (SQLite has no schemas). See ``engine.py``.
WEB_SCHEMA = "web"


class WebBase(DeclarativeBase):
    """Declarative base for website-owned (non-finance) tables."""

    pass


class Conversation(WebBase):
    """A single chat conversation. PK is the client-generated UUID.

    NOTE: ``account_id`` is intentionally absent. It is a future additive
    column (added when the product grows per-account conversations); there is
    no ``accounts`` table in this rollout.
    """

    __tablename__ = "conversations"
    __table_args__ = {"schema": WEB_SCHEMA}

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # Tenant scoping (set at creation, immutable). ``session_mode`` derives
    # visibility: ``individual`` → owner-only, ``joint`` → household-shared.
    # On Postgres these are also fenced by the ``tenant_isolation`` RLS policy
    # (migration 019); on SQLite dev the store's app-layer filter is the only
    # tenant layer.
    household_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    session_mode: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'individual'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    messages: Mapped[list[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class ConversationMessage(WebBase):
    """One message (user or assistant) with its ordered AI SDK ``parts``."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('streaming', 'complete', 'error')",
            name="ck_conversation_messages_status",
        ),
        Index(
            "ix_conv_messages_conv_seq",
            "conversation_id",
            "seq",
        ),
        Index(
            "uq_conv_messages_ai_sdk_id",
            "conversation_id",
            "ai_sdk_message_id",
            unique=True,
            postgresql_where=text("ai_sdk_message_id IS NOT NULL"),
            sqlite_where=text("ai_sdk_message_id IS NOT NULL"),
        ),
        {"schema": WEB_SCHEMA},
    )

    message_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey(f"{WEB_SCHEMA}.conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The Vercel AI SDK (useChat) message id: run_id for assistant turns, the
    # client-minted UUID for user turns. Drives idempotent upsert.
    ai_sdk_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # user / assistant
    parts: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'complete'")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )
