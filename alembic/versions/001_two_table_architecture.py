"""Two-table transaction architecture with Amazon splitting support

Revision ID: 001_two_table_architecture
Revises:
Create Date: 2025-12-31

Refactor from single transactions table to two tables:
- plaid_transactions: Immutable source data from Plaid
- derived_transactions: Mutable, enriched transactions for queries

This enables Amazon transaction splitting (1 Plaid → N derived) and
preserves user edits during regeneration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_two_table_architecture'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create new two-table architecture."""

    # Create plaid_transactions table
    op.create_table(
        'plaid_transactions',
        sa.Column('plaid_transaction_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=False),
        sa.Column('posted_at', sa.Date(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('merchant_descriptor', sa.Text(), nullable=True),
        sa.Column('institution', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('plaid_transaction_id'),
        sa.UniqueConstraint('external_id', 'source', name='uq_plaid_transactions_external_source')
    )

    # Create indexes on plaid_transactions
    op.create_index('idx_plaid_transactions_external', 'plaid_transactions', ['external_id', 'source'])
    op.create_index('idx_plaid_transactions_posted', 'plaid_transactions', ['posted_at'])

    # Create derived_transactions table
    op.create_table(
        'derived_transactions',
        sa.Column('transaction_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('plaid_transaction_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('posted_at', sa.Date(), nullable=False),
        sa.Column('merchant_descriptor', sa.Text(), nullable=True),
        sa.Column('merchant_id', sa.Integer(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('transaction_id'),
        sa.UniqueConstraint('external_id', name='uq_derived_transactions_external_id'),
        sa.ForeignKeyConstraint(['plaid_transaction_id'], ['plaid_transactions.plaid_transaction_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['merchant_id'], ['merchants.merchant_id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.category_id'])
    )

    # Create indexes on derived_transactions
    op.create_index('idx_derived_transactions_plaid', 'derived_transactions', ['plaid_transaction_id'])
    op.create_index('idx_derived_transactions_posted', 'derived_transactions', ['posted_at'])
    op.create_index('idx_derived_transactions_category', 'derived_transactions', ['category_id'])

    # Update transaction_tags FK to point to derived_transactions
    # First drop the old constraint
    op.drop_constraint('transaction_tags_transaction_id_fkey', 'transaction_tags', type_='foreignkey')

    # Create new FK to derived_transactions
    op.create_foreign_key(
        'transaction_tags_transaction_id_fkey',
        'transaction_tags', 'derived_transactions',
        ['transaction_id'], ['transaction_id'],
        ondelete='CASCADE'
    )

    # Drop old transactions table
    op.drop_table('transactions')


def downgrade() -> None:
    """Downgrade not supported - data would be lost.

    To revert: repopulate from Plaid instead.
    """
    raise NotImplementedError(
        "Downgrade not supported for two-table architecture migration. "
        "Repopulate from Plaid instead."
    )
