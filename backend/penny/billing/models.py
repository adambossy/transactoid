"""Website-owned billing ORM models (credential vault, usage ledger, subsidy).

Registered on the **website** ``WebBase`` (``penny.api.persistence.models``) so
they land in the same ``web`` schema / ``penny_web.db`` file as the conversation
tables — deliberately **not** on the finance ``penny.adapters.db.models.Base``.
That separation is what keeps every one of these secrets and ledgers out of the
agent ``run_sql`` blast radius (AGENTS.local.md agent/website segregation).

All three tables are **owner-scoped**: a row is private to its ``user_id`` even
within a household (no shared arm). On Postgres a ``tenant_isolation`` policy
keyed on ``user_id = current_setting('app.current_user')`` fences reads/writes
(migrations 020/021); on SQLite dev the store's ``user_id ==`` filter is the only
tenant layer. See ``penny.billing.session`` — the billing web-session binds
``app.current_user`` to the **real** user id (never the joint nil sentinel),
because credentials are owner-private regardless of session mode.
"""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from penny.api.persistence.models import WEB_SCHEMA, WebBase


class UserCredential(WebBase):
    """One BYO provider credential per ``(user_id, provider)``.

    ``secret_ciphertext`` is the versioned-envelope ciphertext (never the
    plaintext key/token); ``meta`` carries only non-secret hints — a masked
    ``sk-…last4`` and, for OAuth, the expiry. The secret is decrypted only at
    the outbound-LLM call site and is never returned to the client.
    """

    __tablename__ = "user_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_user_credentials_user_provider"
        ),
        {"schema": WEB_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # api_key | oauth
    secret_ciphertext: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class UsageEvent(WebBase):
    """One row per model completion — the subsidy-metering ledger.

    ``cost_cents`` is the host-priced cost (from the harness ``ModelUsage``
    event) rounded to whole cents; ``remaining`` is derived by summing it.
    Only **subsidized** runs are recorded here — a BYO run bills the user's own
    provider and never touches the subsidy ledger.
    """

    __tablename__ = "usage_events"
    __table_args__ = {"schema": WEB_SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class UserBilling(WebBase):
    """Per-user subsidy record — one row per user, created on first grant.

    ``subsidy_granted_cents`` is the cumulative grant (each Plaid-link grant is
    idempotent per user). ``spend_cents`` is derived by summing ``usage_events``;
    remaining runway is ``subsidy_granted_cents - spend``.
    """

    __tablename__ = "user_billing"
    __table_args__ = {"schema": WEB_SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    subsidy_granted_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
