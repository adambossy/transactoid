"""Tighten web.conversations tenant columns to NOT NULL (Postgres only)

Revision ID: 025_tighten_web_conversation_tenancy
Revises: 024_tenant_guc_wrapper
Create Date: 2026-07-12

Migration 019 added ``web.conversations.household_id`` / ``owner_user_id`` as
*nullable* — deliberately, so the phase-3 cutover could backfill existing rows
before tightening (the finance 012→013→014 pattern). But that tightening was
only ever performed by the one-off cutover script, which never runs on a fresh,
alembic-only Postgres DB. The chain therefore left these columns nullable while
``WebBase`` declares them ``nullable=False`` — a real drift between a fresh
Postgres schema and the models (the drift ``test_fresh_postgres_builds_web_
schema_matching_models`` now checks nullability, not just column names).

This revision is finance's 014 for the web schema: it lands the tightening *in
the chain* so a fresh DB converges on the model shape, and it is a safe no-op on
prod (the cutover already backfilled every conversation, so no row violates the
constraint; an unbackfilled row would fail the release loudly rather than
silently — the defined seam). SQLite dev/tests skip this: create_all already
builds the columns NOT NULL from the model.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "025_tighten_web_conversation_tenancy"
down_revision: str | Sequence[str] | None = "024_tenant_guc_wrapper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for column in ("household_id", "owner_user_id"):
        op.alter_column(
            "conversations",
            column,
            existing_type=sa.Uuid(),
            nullable=False,
            schema="web",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for column in ("household_id", "owner_user_id"):
        op.alter_column(
            "conversations",
            column,
            existing_type=sa.Uuid(),
            nullable=True,
            schema="web",
        )
