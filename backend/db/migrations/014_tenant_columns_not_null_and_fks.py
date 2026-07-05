"""Tighten tenant columns: NOT NULL, FKs, CHECKs, indexes (contract phase)

Revision ID: 014_tenant_columns_not_null_and_fks
Revises: 013_backfill_tenant_columns
Create Date: 2026-07-03

Contract half of expand->backfill->contract: the tenant columns added by 012
become NOT NULL with FKs to households/users, a visibility CHECK, and a
nil-UUID CHECK on owner_user_id (the joint-session sentinel must never own a
row — RLS compares owner to app.current_user, which IS the nil UUID in joint
mode). Composite (household_id, owner_user_id) indexes support the RLS/app
filters. Uses batch_alter_table so SQLite (table recreate) and Postgres
(plain ALTER) both work.

The nil-UUID literal is dashless: SQLAlchemy's Uuid stores CHAR(32) hex on
SQLite, and Postgres accepts the dashless form for uuid input.
NOTE: mirrored by ``_tenant_constraints`` in penny/adapters/db/models.py;
keep both in sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_tenant_columns_not_null_and_fks"
down_revision: str | Sequence[str] | None = "013_backfill_tenant_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_VIS = [
    "plaid_transactions",
    "derived_transactions",
    "transaction_items",
    "transaction_tags",
    "email_receipts",
    "pending_receipt_matches",
    "account_sign_conventions",
    "amazon_login_profiles",
    "amazon_orders",
    "amazon_items",
]
HOUSEHOLD_ONLY = ["tags", "transaction_category_events"]
NIL_UUID = "00000000000000000000000000000000"


def upgrade() -> None:
    for t in OWNER_VIS:
        with op.batch_alter_table(t) as batch:
            batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=False)
            batch.alter_column("owner_user_id", existing_type=sa.Uuid(), nullable=False)
            batch.alter_column("visibility", existing_type=sa.String(), nullable=False)
            batch.create_foreign_key(
                f"fk_{t}_household", "households", ["household_id"], ["household_id"]
            )
            batch.create_foreign_key(
                f"fk_{t}_owner_user", "users", ["owner_user_id"], ["user_id"]
            )
            batch.create_check_constraint(
                f"ck_{t}_visibility", "visibility IN ('private', 'shared')"
            )
            batch.create_check_constraint(
                f"ck_{t}_owner_not_nil", f"owner_user_id != '{NIL_UUID}'"
            )
        op.create_index(f"ix_{t}_household_owner", t, ["household_id", "owner_user_id"])

    with op.batch_alter_table("plaid_items") as batch:
        batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("owner_user_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_plaid_items_household", "households", ["household_id"], ["household_id"]
        )
        batch.create_foreign_key(
            "fk_plaid_items_owner_user", "users", ["owner_user_id"], ["user_id"]
        )
        batch.create_check_constraint(
            "ck_plaid_items_owner_not_nil", f"owner_user_id != '{NIL_UUID}'"
        )
    op.create_index(
        "ix_plaid_items_household_owner",
        "plaid_items",
        ["household_id", "owner_user_id"],
    )

    for t in HOUSEHOLD_ONLY:
        with op.batch_alter_table(t) as batch:
            batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(
                f"fk_{t}_household", "households", ["household_id"], ["household_id"]
            )
        op.create_index(f"ix_{t}_household", t, ["household_id"])

    # plaid_accounts was created NOT NULL with FKs (011); add the CHECKs + index
    # it shares with the denormalized tables.
    with op.batch_alter_table("plaid_accounts") as batch:
        batch.create_check_constraint(
            "ck_plaid_accounts_visibility", "visibility IN ('private', 'shared')"
        )
        batch.create_check_constraint(
            "ck_plaid_accounts_owner_not_nil", f"owner_user_id != '{NIL_UUID}'"
        )
    op.create_index(
        "ix_plaid_accounts_household_owner",
        "plaid_accounts",
        ["household_id", "owner_user_id"],
    )

    # A user must never be created AS the joint sentinel.
    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint(
            "ck_users_user_id_not_nil", f"user_id != '{NIL_UUID}'"
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_user_id_not_nil", type_="check")

    op.drop_index("ix_plaid_accounts_household_owner", table_name="plaid_accounts")
    with op.batch_alter_table("plaid_accounts") as batch:
        batch.drop_constraint("ck_plaid_accounts_owner_not_nil", type_="check")
        batch.drop_constraint("ck_plaid_accounts_visibility", type_="check")

    for t in HOUSEHOLD_ONLY:
        op.drop_index(f"ix_{t}_household", table_name=t)
        with op.batch_alter_table(t) as batch:
            batch.drop_constraint(f"fk_{t}_household", type_="foreignkey")
            batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=True)

    op.drop_index("ix_plaid_items_household_owner", table_name="plaid_items")
    with op.batch_alter_table("plaid_items") as batch:
        batch.drop_constraint("ck_plaid_items_owner_not_nil", type_="check")
        batch.drop_constraint("fk_plaid_items_owner_user", type_="foreignkey")
        batch.drop_constraint("fk_plaid_items_household", type_="foreignkey")
        batch.alter_column("owner_user_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=True)

    for t in OWNER_VIS:
        op.drop_index(f"ix_{t}_household_owner", table_name=t)
        with op.batch_alter_table(t) as batch:
            batch.drop_constraint(f"ck_{t}_owner_not_nil", type_="check")
            batch.drop_constraint(f"ck_{t}_visibility", type_="check")
            batch.drop_constraint(f"fk_{t}_owner_user", type_="foreignkey")
            batch.drop_constraint(f"fk_{t}_household", type_="foreignkey")
            batch.alter_column("visibility", existing_type=sa.String(), nullable=True)
            batch.alter_column("owner_user_id", existing_type=sa.Uuid(), nullable=True)
            batch.alter_column("household_id", existing_type=sa.Uuid(), nullable=True)
