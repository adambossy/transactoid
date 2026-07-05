"""Add the workspace store tables (prefix/manifest/head) with RLS

Revision ID: 018_add_workspace_store
Revises: 017_encrypt_plaid_access_tokens
Create Date: 2026-07-04

Phase 1b: the Postgres side of the hybrid workspace. Three RLS-protected
tables broker access to content-addressed blobs in R2 —
``workspace_prefixes`` (opaque-token directories, one shared per household +
one private per user, partial-unique-enforced), ``workspace_manifests`` (the
append-only per-prefix version chain), and ``workspace_heads`` (the
compare-and-set target advanced on flush). All three carry the
household/owner/visibility triple and get the phase-1a ``tenant_isolation``
policy (USING **and** WITH CHECK) + ``FORCE ROW LEVEL SECURITY`` on Postgres;
SQLite gets the tables/constraints only (no RLS there, app-level filtering is
the tenant layer). The policy shape is the single source in
``penny.adapters.db.rls`` — the same module the ``pg_db`` test fixture uses.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_add_workspace_store"
down_revision: str | Sequence[str] | None = "017_encrypt_plaid_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE_TABLES = (
    "workspace_manifests",
    "workspace_heads",
    "workspace_prefixes",
)


def upgrade() -> None:
    op.create_table(
        "workspace_prefixes",
        sa.Column("prefix_token", sa.String(), primary_key=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["household_id"], ["households.household_id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.user_id"]),
        sa.CheckConstraint(
            "visibility IN ('private', 'shared')",
            name="ck_workspace_prefixes_visibility",
        ),
        sa.CheckConstraint(
            "kind IN ('private', 'shared')",
            name="ck_workspace_prefixes_kind",
        ),
    )
    # One shared prefix per household; one private prefix per user.
    op.create_index(
        "uq_workspace_prefix_shared_per_household",
        "workspace_prefixes",
        ["household_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'shared'"),
        postgresql_where=sa.text("kind = 'shared'"),
    )
    op.create_index(
        "uq_workspace_prefix_private_per_owner",
        "workspace_prefixes",
        ["owner_user_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'private'"),
        postgresql_where=sa.text("kind = 'private'"),
    )

    op.create_table(
        "workspace_manifests",
        sa.Column("manifest_id", sa.Uuid(), primary_key=True),
        sa.Column("prefix_token", sa.String(), nullable=False),
        sa.Column("parent_manifest_id", sa.Uuid(), nullable=True),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["prefix_token"], ["workspace_prefixes.prefix_token"]),
        sa.CheckConstraint(
            "visibility IN ('private', 'shared')",
            name="ck_workspace_manifests_visibility",
        ),
    )
    op.create_index(
        "ix_workspace_manifests_prefix", "workspace_manifests", ["prefix_token"]
    )

    op.create_table(
        "workspace_heads",
        sa.Column("prefix_token", sa.String(), primary_key=True),
        sa.Column("head_manifest_id", sa.Uuid(), nullable=True),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["prefix_token"], ["workspace_prefixes.prefix_token"]),
        sa.CheckConstraint(
            "visibility IN ('private', 'shared')",
            name="ck_workspace_heads_visibility",
        ),
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from penny.adapters.db.rls import household_policy_ddl

    for table in ("workspace_prefixes", "workspace_manifests", "workspace_heads"):
        for ddl in household_policy_ddl(table, owner_vis=True):
            op.execute(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _WORKSPACE_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table in _WORKSPACE_TABLES:
        op.drop_table(table)
