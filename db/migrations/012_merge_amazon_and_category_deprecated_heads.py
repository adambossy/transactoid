"""Merge amazon and category-deprecated heads into a single linear history.

Revision ID: 012_merge_amazon_and_category_deprecated_heads
Revises: 011_add_history_complete_through, 010_add_category_deprecated
Create Date: 2026-05-23

The graph forks at 008_add_web_search_summary:

    008 -> 009_add_amazon_login_profiles -> 010_add_profile_id_to_amazon_orders
       -> 011_add_history_complete_through                       (amazon head)

    008 -> 010_add_category_deprecated                            (deprecated head)

Both heads were applied to production out-of-band, leaving Alembic with two
heads. This no-op revision joins them so future migrations can chain off a
single head.
"""

# revision identifiers, used by Alembic.
revision: str = "012_merge_amazon_and_category_deprecated_heads"
down_revision: str | tuple[str, str] | None = (
    "011_add_history_complete_through",
    "010_add_category_deprecated",
)
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Merge-only migration; no schema changes."""


def downgrade() -> None:
    """Merge-only migration; no schema changes."""
