"""Dev/test backfill of tenant columns onto pre-tenancy data.

Called by migration 013 (opt-in via ``PENNY_DEV_BACKFILL=1``) between the
expand (012) and contract (014) migrations. Prod ownership is assigned by the
phase-3 cutover, never by this module — see the migration's docstring.

Idempotent: identity rows are inserted only if missing, and tenant columns are
only filled where NULL.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

# Tables that carry the full owner/visibility triple (mirrors migration 012).
OWNER_VIS_TABLES = [
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
# Tables scoped to the household only (plaid_items additionally carries
# owner_user_id, handled separately — it has no visibility column).
HOUSEHOLD_ONLY_TABLES = ["plaid_items", "tags", "transaction_category_events"]


def _stmt(sql: str, *uuid_names: str) -> sa.TextClause:
    """A text() statement with the named params typed as Uuid.

    Plain text() binds pass uuid.UUID objects straight to the driver, which
    SQLite rejects; typing them serializes exactly as the Uuid columns do.
    """
    return sa.text(sql).bindparams(
        *(sa.bindparam(n, type_=sa.Uuid()) for n in uuid_names)
    )


def backfill_household(
    session: Session,
    *,
    household_id: uuid.UUID,
    name: str,
    user1: tuple[uuid.UUID, str],
    user2: tuple[uuid.UUID, str],
) -> None:
    """Assign every pre-tenancy row to one household, owned by ``user1``.

    Creates the household and both users if missing, materializes a
    ``plaid_accounts`` row (owner=user1, private) for each distinct
    ``(account_id, item_id)`` seen in ``plaid_transactions``, then fills every
    NULL tenant column with household / user1 / ``'private'``.
    """
    user1_id, user1_email = user1
    user2_id, user2_email = user2

    exists = session.execute(
        _stmt("SELECT 1 FROM households WHERE household_id = :h", "h"),
        {"h": household_id},
    ).first()
    if not exists:
        session.execute(
            _stmt("INSERT INTO households (household_id, name) VALUES (:h, :n)", "h"),
            {"h": household_id, "n": name},
        )
    for user_id, email in [(user1_id, user1_email), (user2_id, user2_email)]:
        exists = session.execute(
            _stmt("SELECT 1 FROM users WHERE user_id = :u", "u"), {"u": user_id}
        ).first()
        if not exists:
            session.execute(
                _stmt(
                    "INSERT INTO users (user_id, household_id, email) "
                    "VALUES (:u, :h, :e)",
                    "u",
                    "h",
                ),
                {"u": user_id, "h": household_id, "e": email},
            )

    accounts = session.execute(
        sa.text(
            "SELECT DISTINCT account_id, item_id FROM plaid_transactions "
            "WHERE item_id IS NOT NULL"
        )
    ).all()
    for account_id, item_id in accounts:
        exists = session.execute(
            sa.text("SELECT 1 FROM plaid_accounts WHERE account_id = :a"),
            {"a": account_id},
        ).first()
        if not exists:
            session.execute(
                _stmt(
                    "INSERT INTO plaid_accounts "
                    "(account_id, item_id, owner_user_id, household_id, visibility) "
                    "VALUES (:a, :i, :u, :h, 'private')",
                    "u",
                    "h",
                ),
                {"a": account_id, "i": item_id, "u": user1_id, "h": household_id},
            )

    for t in OWNER_VIS_TABLES:
        session.execute(
            _stmt(
                f"UPDATE {t} SET household_id = :h WHERE household_id IS NULL",  # noqa: S608
                "h",
            ),
            {"h": household_id},
        )
        session.execute(
            _stmt(
                f"UPDATE {t} SET owner_user_id = :u WHERE owner_user_id IS NULL",  # noqa: S608
                "u",
            ),
            {"u": user1_id},
        )
        session.execute(
            sa.text(
                f"UPDATE {t} SET visibility = 'private' WHERE visibility IS NULL"  # noqa: S608
            )
        )
    for t in HOUSEHOLD_ONLY_TABLES:
        session.execute(
            _stmt(
                f"UPDATE {t} SET household_id = :h WHERE household_id IS NULL",  # noqa: S608
                "h",
            ),
            {"h": household_id},
        )
    session.execute(
        _stmt(
            "UPDATE plaid_items SET owner_user_id = :u WHERE owner_user_id IS NULL",
            "u",
        ),
        {"u": user1_id},
    )
