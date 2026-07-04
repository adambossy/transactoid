"""Tag names unique per household, not globally

Revision ID: 027_tags_unique_per_household
Revises: 026_add_message_sender
Create Date: 2026-07-16

Tags are household-scoped (household_id NOT NULL + household-only RLS since
014/015), but the baseline's global UNIQUE(name) survived — so one
household's tag name blocked every other household from using it (and the
collision error doubled as a cross-tenant tag-name oracle). Uniqueness moves
to (household_id, name).

The baseline constraint was unnamed: Postgres auto-named it tags_name_key;
on SQLite, batch mode names the reflected constraint via naming_convention.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "027_tags_unique_per_household"
down_revision: str | Sequence[str] | None = "026_add_message_sender"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("tags_name_key", "tags", type_="unique")
        op.create_unique_constraint(
            "uq_tags_household_name", "tags", ["household_id", "name"]
        )
    else:
        with op.batch_alter_table("tags", naming_convention=_SQLITE_NAMING) as batch:
            batch.drop_constraint("uq_tags_name", type_="unique")
            batch.create_unique_constraint(
                "uq_tags_household_name", ["household_id", "name"]
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("uq_tags_household_name", "tags", type_="unique")
        op.create_unique_constraint("tags_name_key", "tags", ["name"])
    else:
        with op.batch_alter_table("tags", naming_convention=_SQLITE_NAMING) as batch:
            batch.drop_constraint("uq_tags_household_name", type_="unique")
            batch.create_unique_constraint("uq_tags_name", ["name"])
