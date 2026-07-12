"""Add sender attribution to web conversation messages

Revision ID: 025_add_message_sender
Revises: 024_tenant_guc_wrapper
Create Date: 2026-07-12

A joint (household-shared) conversation is written by more than one member, but
``web.conversation_messages`` recorded only ``role`` — every user turn was
anonymous. This revision adds a nullable ``sender_user_id`` so the UI can
attribute each user turn to the member who wrote it. Nullable on purpose:
assistant turns and pre-existing rows legitimately have no sender, so there is
no backfill and the column lands as an instant catalog change. Bare uuid, no
cross-schema FK — mirrors ``web.conversations.owner_user_id``.

No RLS change: messages inherit their conversation's visibility (migration
019's parent-subquery predicate), and a new column does not alter that.

SQLite dev/tests skip this entirely: the column comes from the model via
``create_all``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "025_add_message_sender"
down_revision: str | Sequence[str] | None = "024_tenant_guc_wrapper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MSGS = "web.conversation_messages"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_MSGS} ADD COLUMN IF NOT EXISTS sender_user_id uuid")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_MSGS} DROP COLUMN IF EXISTS sender_user_id")
