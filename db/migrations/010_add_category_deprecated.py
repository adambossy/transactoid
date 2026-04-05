"""Add deprecated_at column to categories

Revision ID: 010_add_category_deprecated
Revises: 008_add_web_search_summary
Create Date: 2026-04-05

Adds a nullable timestamp deprecated_at column to the categories table so that
retired subcategories can be soft-deleted while preserving FK
integrity with the transaction_category_events audit log.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_category_deprecated"
down_revision: str | Sequence[str] | None = "008_add_web_search_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add deprecated_at nullable timestamp column."""
    op.add_column(
        "categories",
        sa.Column(
            "deprecated_at",
            sa.TIMESTAMP(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove deprecated_at column."""
    op.drop_column("categories", "deprecated_at")
