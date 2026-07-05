"""Backfill tenant columns (dev/test opt-in only)

Revision ID: 013_backfill_tenant_columns
Revises: 012_add_tenant_columns_nullable
Create Date: 2026-07-03

Data-only migration between expand (012) and contract (014). It is a no-op
unless ``PENNY_DEV_BACKFILL=1``: on prod, ownership of legacy rows is assigned
interactively by the phase-3 cutover — exactly one mechanism creates prod
identity — and this revision merely passes through. With the opt-in set
(local/CI), it creates the dev household + two users from ``PENNY_DEV_*`` env
and assigns every pre-tenancy row to them so 014's NOT NULL contract can apply
on a populated dev DB.
"""

from collections.abc import Sequence
import os
import uuid

from sqlalchemy.orm import Session

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_backfill_tenant_columns"
down_revision: str | Sequence[str] | None = "012_add_tenant_columns_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if os.environ.get("PENNY_DEV_BACKFILL", "").strip() != "1":
        return

    from penny.db_backfill import backfill_household

    household_id = uuid.UUID(os.environ["PENNY_DEV_HOUSEHOLD_ID"])
    user1 = (
        uuid.UUID(os.environ["PENNY_DEV_USER_ID"]),
        os.environ["PENNY_DEV_USER_EMAIL"],
    )
    user2 = (
        uuid.UUID(os.environ["PENNY_DEV_USER2_ID"]),
        os.environ["PENNY_DEV_USER2_EMAIL"],
    )
    with Session(bind=op.get_bind()) as session:
        backfill_household(
            session,
            household_id=household_id,
            name=os.environ.get("PENNY_DEV_HOUSEHOLD_NAME", "Dev Household"),
            user1=user1,
            user2=user2,
        )
        session.commit()


def downgrade() -> None:
    # Data migrations don't reverse.
    pass
