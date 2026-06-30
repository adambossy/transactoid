"""merge divergent migration heads

Revision ID: 008_merge_heads
Revises: 006_add_is_hidden_to_derived_transactions, 007_add_eval_store, 007_add_original_descriptor_to_plaid_transactions
Create Date: 2026-06-30 08:26:36.799330

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "008_merge_heads"
down_revision: str | Sequence[str] | None = (
    "006_add_is_hidden_to_derived_transactions",
    "007_add_eval_store",
    "007_add_original_descriptor_to_plaid_transactions",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
