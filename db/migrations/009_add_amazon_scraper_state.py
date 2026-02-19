"""Add amazon_scraper_state table for persisted Browserbase context.

Revision ID: 009_add_amazon_scraper_state
Revises: 008_add_web_search_summary
Create Date: 2026-02-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_add_amazon_scraper_state"
down_revision: str | Sequence[str] | None = "008_add_web_search_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create amazon_scraper_state table."""
    op.create_table(
        "amazon_scraper_state",
        sa.Column("state_id", sa.Integer(), nullable=False),
        sa.Column("browserbase_context_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("state_id"),
    )


def downgrade() -> None:
    """Drop amazon_scraper_state table."""
    op.drop_table("amazon_scraper_state")
