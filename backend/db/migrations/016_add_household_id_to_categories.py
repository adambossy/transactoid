"""Per-household taxonomy: categories.household_id + scoped unique key

Revision ID: 016_add_household_id_to_categories
Revises: 015_enable_rls_policies
Create Date: 2026-07-03

Adds ``household_id`` to categories (nullable -> dev backfill -> NOT NULL +
FK), replaces the active-key unique index with ``(household_id, key) WHERE
deprecated_at IS NULL``, and enables the household-only RLS policy (the
column must exist before the policy can reference it, so the policy lands
here rather than in 015).

Backfill reads ``PENNY_DEV_HOUSEHOLD_ID`` — dev/test only, mirroring
migration 013. On prod, rows are assigned by the phase-3 cutover before this
contract applies; running it with unassigned rows fails loudly on NOT NULL
rather than guessing an owner.
"""

from collections.abc import Sequence
import os
import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_add_household_id_to_categories"
down_revision: str | Sequence[str] | None = "015_enable_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("household_id", sa.Uuid(), nullable=True))

    household_raw = os.environ.get("PENNY_DEV_HOUSEHOLD_ID", "").strip()
    if household_raw:
        household_id = uuid.UUID(household_raw)
        bind = op.get_bind()
        exists = bind.execute(
            sa.text("SELECT 1 FROM households WHERE household_id = :h").bindparams(
                sa.bindparam("h", type_=sa.Uuid())
            ),
            {"h": household_id},
        ).first()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO households (household_id, name) VALUES (:h, :n)"
                ).bindparams(sa.bindparam("h", type_=sa.Uuid())),
                {"h": household_id, "n": "Dev Household"},
            )
        bind.execute(
            sa.text(
                "UPDATE categories SET household_id = :h WHERE household_id IS NULL"
            ).bindparams(sa.bindparam("h", type_=sa.Uuid())),
            {"h": household_id},
        )

    op.drop_index("uq_categories_key_active", table_name="categories")
    with op.batch_alter_table("categories") as batch:
        batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_categories_household",
            "households",
            ["household_id"],
            ["household_id"],
        )
    op.create_index(
        "uq_categories_household_key_active",
        "categories",
        ["household_id", "key"],
        unique=True,
        postgresql_where=sa.text("deprecated_at IS NULL"),
        sqlite_where=sa.text("deprecated_at IS NULL"),
    )

    if op.get_bind().dialect.name == "postgresql":
        from penny.adapters.db.rls import household_policy_ddl

        for ddl in household_policy_ddl("categories", owner_vis=False):
            op.execute(ddl)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON categories")
        op.execute("ALTER TABLE categories DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_categories_household_key_active", table_name="categories")
    with op.batch_alter_table("categories") as batch:
        batch.drop_constraint("fk_categories_household", type_="foreignkey")
    op.create_index(
        "uq_categories_key_active",
        "categories",
        ["key"],
        unique=True,
        postgresql_where=sa.text("deprecated_at IS NULL"),
        sqlite_where=sa.text("deprecated_at IS NULL"),
    )
    op.drop_column("categories", "household_id")
