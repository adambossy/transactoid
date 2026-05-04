"""Refund service: link a refund derived_transaction to the charge it offsets.

Public API
----------
    record_refund(db, refund_txn_id, original_txn_id, matched_by) -> RefundResult

All validation and the DB write happen atomically in one session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import loguru
from loguru import logger

from transactoid.adapters.db.models import DerivedTransaction
from transactoid.errors import RefundError

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB

# Maximum number of days a refund may pre-date the original before rejection.
# A small window accommodates posting-order quirks between institutions.
_MAX_PREDATE_DAYS = 1


@dataclass(frozen=True, slots=True)
class RefundResult:
    """Return value from record_refund containing amounts and any advisory warnings."""

    refund_amount_cents: int
    original_amount_cents: int
    warnings: list[str] = field(default_factory=list)


def record_refund(
    db: DB,
    *,
    refund_txn_id: int,
    original_txn_id: int,
    matched_by: Literal["user", "auto"] = "user",
    _logger: loguru.Logger = logger,
) -> RefundResult:
    """Link a refund derived_transaction to the original charge it offsets.

    Validations (in order):
    - Both transaction IDs must exist.
    - The refund row must not be linked to itself.
    - Neither row may be ``is_verified=True``.
    - The refund row must not already be linked to a *different* original.
    - ``refund_txn.posted_at >= original_txn.posted_at - 1 day`` (grace window).
    - The underlying plaid transactions must share the same ``currency``.
    - Account mismatch: allowed but logged as a WARNING and included in result.
    - Positive ``amount_cents`` on the refund row: allowed but logged as a WARNING
      and included in result.

    The entire operation runs inside a single session and is rolled back if any
    step fails.

    Args:
        db: Database facade.
        refund_txn_id: PK of the derived_transaction that is the refund.
        original_txn_id: PK of the derived_transaction being refunded.
        matched_by: Who created the link — 'user' (CLI) or 'auto' (pipeline).
        _logger: Injectable logger for testability; defaults to module logger.

    Returns:
        RefundResult with the refund and original amount_cents and any warnings.

    Raises:
        RefundError: On any validation failure.
    """
    with db.session() as session:
        refund_row = session.get(DerivedTransaction, refund_txn_id)
        if refund_row is None:
            raise RefundError(f"transaction {refund_txn_id} not found")

        original_row = session.get(DerivedTransaction, original_txn_id)
        if original_row is None:
            raise RefundError(f"transaction {original_txn_id} not found")

        if refund_txn_id == original_txn_id:
            raise RefundError(f"transaction {refund_txn_id} cannot be linked to itself")

        if refund_row.is_verified:
            raise RefundError(
                f"transaction {refund_txn_id} is verified and cannot be modified; "
                "un-verify first"
            )
        if original_row.is_verified:
            raise RefundError(
                f"transaction {original_txn_id} is verified and cannot be modified; "
                "un-verify first"
            )

        # Reject if the refund is already linked to a *different* original.
        existing_link = refund_row.refund_of_transaction_id
        if existing_link is not None and existing_link != original_txn_id:
            raise RefundError(
                f"transaction {refund_txn_id} is already linked to "
                f"transaction {existing_link}; unlink it first"
            )

        # Refund must not substantially pre-date the original.
        earliest_allowed = original_row.posted_at - timedelta(days=_MAX_PREDATE_DAYS)
        if refund_row.posted_at < earliest_allowed:
            raise RefundError(
                f"refund posted_at {refund_row.posted_at} predates "
                f"original posted_at {original_row.posted_at} by more than "
                f"{_MAX_PREDATE_DAYS} day(s); cannot link"
            )

        # Currency must match (compare on the underlying plaid rows).
        refund_plaid = refund_row.plaid_transaction
        original_plaid = original_row.plaid_transaction
        if refund_plaid.currency != original_plaid.currency:
            raise RefundError(
                f"currency mismatch: refund is {refund_plaid.currency}, "
                f"original is {original_plaid.currency}"
            )

        warnings: list[str] = []

        # Account mismatch is allowed but noteworthy.
        if refund_plaid.account_id != original_plaid.account_id:
            msg = (
                f"Refund TXN-{refund_txn_id} and original TXN-{original_txn_id} "
                "are on different accounts; linking anyway"
            )
            _logger.bind(
                refund_txn_id=refund_txn_id,
                original_txn_id=original_txn_id,
                refund_account_id=refund_plaid.account_id,
                original_account_id=original_plaid.account_id,
            ).warning(msg)
            warnings.append(msg)

        # Warn if the "refund" row has a positive amount — unusual.
        if refund_row.amount_cents > 0:
            msg = (
                f"Refund TXN-{refund_txn_id} has positive amount_cents "
                f"({refund_row.amount_cents}); "
                "expected a negative value — linking anyway"
            )
            _logger.bind(
                refund_txn_id=refund_txn_id,
                amount_cents=refund_row.amount_cents,
            ).warning(msg)
            warnings.append(msg)

        refund_amount_cents = refund_row.amount_cents
        original_amount_cents = original_row.amount_cents
        matched_at = datetime.now(UTC)

        db.create_refund_link(
            session, refund_txn_id, original_txn_id, matched_by, matched_at
        )

    return RefundResult(
        refund_amount_cents=refund_amount_cents,
        original_amount_cents=original_amount_cents,
        warnings=warnings,
    )
