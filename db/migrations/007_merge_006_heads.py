"""Merge 006 heads into a single linear history.

Revision ID: 007_merge_006_heads
Revises: 006_add_category_provenance, 006_add_investments_support
Create Date: 2026-02-12
"""

# revision identifiers, used by Alembic.
revision: str = "007_merge_006_heads"
down_revision: str | tuple[str, str] | None = (
    "006_add_category_provenance",
    "006_add_investments_support",
)
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Merge-only migration; no schema changes."""


def downgrade() -> None:
    """Merge-only migration; no schema changes."""
