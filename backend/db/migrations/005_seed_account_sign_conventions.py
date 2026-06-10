"""Seed account_sign_conventions from institution mapping

Revision ID: 005_seed_account_sign_conventions
Revises: 004_add_account_sign_conventions
Create Date: 2026-05-01

DATA MIGRATION ONLY — no DDL changes.

Populates account_sign_conventions for every distinct account_id present in
plaid_transactions, using the empirically-determined institution -> sign_convention
mapping in penny.adapters.db.sign_convention_defaults.

EMPIRICAL BASIS: This mapping was derived by inspecting the user's actual
production data. The sign conventions here are NOT authoritative for all
deployments — they reflect which institutions were observed to report expenses
as positive vs. negative amounts in this specific user's transaction history.
If you are running this on a different dataset, verify the conventions before
running upgrade().

DEFAULT: Any account whose institution is NULL (e.g., CSV-sourced rows) or
whose institution name is not in the mapping gets 'expense_positive', which
matches the Plaid API documentation's stated default behaviour.

Institution names are matched verbatim. `plaid_transactions.institution`
must equal the dict key exactly (case-sensitive, whitespace-significant).
New institutions are silently mapped to the default; verify by querying
`account_sign_conventions WHERE provenance='seeded' AND notes LIKE
'Seeded from institution=...'` after seeding.

IDEMPOTENCY: Uses ON CONFLICT DO NOTHING semantics — accounts that already
have a row in account_sign_conventions (e.g., from a prior manual override)
are left unchanged. Re-running this migration is safe.

DOWNGRADE: Removes only rows with provenance='seeded'. Manual overrides
(provenance='manual') are preserved.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_seed_account_sign_conventions"
down_revision: str | Sequence[str] | None = "004_add_account_sign_conventions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Seed account_sign_conventions for existing plaid_transactions accounts."""
    from sqlalchemy.orm import Session

    from penny.adapters.db.models import (  # noqa: PLC0415
        AccountSignConvention,
        PlaidTransaction,
    )
    from penny.adapters.db.sign_convention_defaults import (  # noqa: PLC0415
        DEFAULT_SIGN_CONVENTION,
        INSTITUTION_SIGN_CONVENTIONS,
    )

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        # Collect distinct (account_id, institution) pairs from the source table.
        rows = (
            session.query(PlaidTransaction.account_id, PlaidTransaction.institution)
            .distinct()
            .all()
        )
        pairs: list[tuple[str, str | None]] = [
            (str(row.account_id), row.institution) for row in rows
        ]

        # Batch existence check — one query for all account_ids.
        account_ids = [account_id for account_id, _ in pairs]
        existing_ids: set[str] = set()
        if account_ids:
            existing_rows = (
                session.query(AccountSignConvention.account_id)
                .filter(AccountSignConvention.account_id.in_(account_ids))
                .all()
            )
            existing_ids = {str(r.account_id) for r in existing_rows}

        for account_id, institution in pairs:
            # ON CONFLICT DO NOTHING: skip accounts already in the table.
            if account_id in existing_ids:
                continue

            if institution is not None and institution in INSTITUTION_SIGN_CONVENTIONS:
                convention = INSTITUTION_SIGN_CONVENTIONS[institution]
            else:
                # NULL institution (CSV-sourced) or unknown institution — use default.
                convention = DEFAULT_SIGN_CONVENTION

            notes = f"Seeded from institution={institution!r}"
            row = AccountSignConvention(
                account_id=account_id,
                sign_convention=convention,
                provenance="seeded",
                notes=notes,
            )
            session.add(row)

        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    """Delete all seeded rows; preserve manual overrides."""
    op.execute("DELETE FROM account_sign_conventions WHERE provenance = 'seeded'")
