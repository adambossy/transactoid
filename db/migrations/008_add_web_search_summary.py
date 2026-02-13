"""Add web_search_summary to derived_transactions

Revision ID: 008_add_web_search_summary
Revises: 007_merge_006_heads
Create Date: 2026-02-09

Adds a nullable text field for storing a concise merchant description learned
from LLM web-search categorization.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_add_web_search_summary"
down_revision: str | Sequence[str] | None = "007_merge_006_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add web_search_summary column."""
    op.add_column(
        "derived_transactions",
        sa.Column("web_search_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove web_search_summary column."""
    op.drop_column("derived_transactions", "web_search_summary")
