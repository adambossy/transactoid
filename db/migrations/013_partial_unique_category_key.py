"""Swap the global UNIQUE on categories.key for a partial unique on active rows.

Revision ID: 013_partial_unique_category_key
Revises: 012_merge_amazon_and_category_deprecated_heads
Create Date: 2026-05-23

The plain `UNIQUE(key)` constraint prevented soft-delete from working: a
deprecated row blocked insert of a new active row with the same key.
Replace it with a partial unique index that only counts active rows:

    UNIQUE(key) WHERE deprecated_at IS NULL

This is supported on Postgres (production) and SQLite >= 3.8 (tests).

Inspector-guarded so the migration is safe to apply against a database
that has drifted (e.g. production already has `deprecated_at` from an
out-of-band run) or is being re-run after partial application.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_partial_unique_category_key"
down_revision: str | Sequence[str] | None = (
    "012_merge_amazon_and_category_deprecated_heads"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Legacy names the column-level UNIQUE may have been assigned by SQLAlchemy or
# manual creation. Postgres auto-names a column-level UNIQUE as
# "<table>_<column>_key"; some scripts may have created an `uq_categories_key`.
_LEGACY_UNIQUE_NAMES: tuple[str, ...] = ("categories_key_key", "uq_categories_key")


def upgrade() -> None:
    """Drop the global unique on `key`; create the partial unique index."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("categories")
        if constraint.get("name")
    }
    indexes = {index["name"] for index in inspector.get_indexes("categories")}

    for name in _LEGACY_UNIQUE_NAMES:
        if name in unique_constraints:
            op.drop_constraint(name, "categories", type_="unique")
        elif name in indexes:
            op.drop_index(name, table_name="categories")

    if "uq_categories_key_active" not in indexes:
        op.create_index(
            "uq_categories_key_active",
            "categories",
            ["key"],
            unique=True,
            postgresql_where=sa.text("deprecated_at IS NULL"),
            sqlite_where=sa.text("deprecated_at IS NULL"),
        )


def downgrade() -> None:
    """Drop the partial unique index; restore the global unique on `key`."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("categories")
        if constraint.get("name")
    }
    indexes = {index["name"] for index in inspector.get_indexes("categories")}

    if "uq_categories_key_active" in indexes:
        op.drop_index("uq_categories_key_active", table_name="categories")

    if "categories_key_key" not in unique_constraints:
        op.create_unique_constraint("categories_key_key", "categories", ["key"])
