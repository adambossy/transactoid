"""Add sync_cursor to plaid_items

Revision ID: fb807f1d4851
Revises: 183c77cd21a4
Create Date: 2025-12-24 23:21:28.431403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb807f1d4851'
down_revision: Union[str, Sequence[str], None] = '183c77cd21a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('plaid_items', sa.Column('sync_cursor', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('plaid_items', 'sync_cursor')
