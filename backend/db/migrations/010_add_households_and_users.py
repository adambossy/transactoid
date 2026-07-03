"""Add households and users

Revision ID: 010_add_households_and_users
Revises: 009_add_plaid_raw_name_and_enrichment
Create Date: 2026-07-03

First migration of the multi-tenant data model (phase 1a). Introduces the
identity tables every financial row will eventually reference: a ``households``
tenant boundary and its member ``users``.

Note on numbering: the phase-1a plan was authored assuming head ``005``; the
chain had since advanced to ``009`` (merchant metadata + plaid enrichment), so
this tenancy chain appends to the real head ``009`` and is numbered ``010``+.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_households_and_users"
down_revision: str | Sequence[str] | None = "009_add_plaid_raw_name_and_enrichment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("household_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("external_auth_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.household_id"]),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("external_auth_id", name="uq_users_external_auth_id"),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("households")
