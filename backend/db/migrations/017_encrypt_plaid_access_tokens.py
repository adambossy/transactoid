"""Encrypt plaid_items.access_token at rest (data-only)

Revision ID: 017_encrypt_plaid_access_tokens
Revises: 016_add_household_id_to_categories
Create Date: 2026-07-03

Encrypts every plaintext access_token with the key-versioned Fernet cipher
(``v1:<fernet>`` — see penny.security.token_cipher). Idempotent: already
encrypted rows are left alone. No-op on an empty/fully-encrypted table; if
plaintext rows exist, PENNY_PLAID_TOKEN_KEY must be set or the migration
fails loudly rather than leaving a mixed state ambiguous.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017_encrypt_plaid_access_tokens"
down_revision: str | Sequence[str] | None = "016_add_household_id_to_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from penny.security.token_cipher import encrypt_token, is_encrypted

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT item_id, access_token FROM plaid_items")).all()
    pending = [(i, t) for i, t in rows if not is_encrypted(t)]
    for item_id, token in pending:
        bind.execute(
            sa.text("UPDATE plaid_items SET access_token = :t WHERE item_id = :i"),
            {"t": encrypt_token(token), "i": item_id},
        )


def downgrade() -> None:
    from penny.security.token_cipher import decrypt_token, is_encrypted

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT item_id, access_token FROM plaid_items")).all()
    for item_id, token in rows:
        if is_encrypted(token):
            bind.execute(
                sa.text("UPDATE plaid_items SET access_token = :t WHERE item_id = :i"),
                {"t": decrypt_token(token), "i": item_id},
            )
