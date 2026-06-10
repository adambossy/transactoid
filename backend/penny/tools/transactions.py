"""Transaction mutation tools: split and refund linking."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from agent_harness import tool

from penny.db import get_db
from penny.errors import RefundError, SplitError
from penny.tools._services.refund import record_refund as _record_refund
from penny.tools._services.split import split_transaction as _split_transaction

_MAX_PART_DOLLARS = 1_000_000.0


def _dollars_to_cents(amount: float) -> int:
    """Convert a dollar amount to cents, enforcing 2-decimal precision."""
    rounded = round(amount, 2)
    return round(rounded * 100)


def _validate_dollar_amounts(amounts: list[float]) -> str | None:
    """Return an error message if any amount is invalid, else None."""
    for idx, amt in enumerate(amounts):
        if amt <= 0:
            return f"amounts[{idx}] must be positive; got {amt}"
        if amt > _MAX_PART_DOLLARS:
            return (
                f"amounts[{idx}] exceeds maximum ${_MAX_PART_DOLLARS:,.0f}; got {amt}"
            )
        # Reject more than 2 decimal places.
        if not math.isclose(amt, round(amt, 2), rel_tol=0, abs_tol=1e-9):
            return f"amounts[{idx}] has more than 2 decimal places: {amt}"
    return None


@tool
async def split_transaction(txn_id: int, amounts: list[float]) -> dict[str, Any]:
    """Split one transaction into multiple parts with explicit dollar amounts.

    Converts dollar amounts to cents before calling the split service. The
    amounts must sum exactly to the original transaction amount.

    Not permitted on Amazon-matched transactions — those are split automatically
    from order data. Verified transactions cannot be split.

    Args:
        txn_id: ID of the derived_transaction to split.
        amounts: Dollar amounts for each part (e.g. [12.50, 7.50]).
            Must be positive, at most 2 decimal places, and sum exactly to
            the original transaction amount.
    """

    def _run() -> dict[str, Any]:
        validation_error = _validate_dollar_amounts(amounts)
        if validation_error:
            return {"status": "error", "message": validation_error}

        parts = [_dollars_to_cents(amt) for amt in amounts]

        try:
            new_ids = _split_transaction(get_db(), txn_id, parts)
            return {
                "status": "success",
                "new_transaction_ids": new_ids,
                "parts": [
                    {"transaction_id": tid, "amount_cents": cents}
                    for tid, cents in zip(new_ids, parts)
                ],
            }
        except SplitError as exc:
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)


@tool
async def record_refund(refund_txn_id: int, original_txn_id: int) -> dict[str, Any]:
    """Link a refund transaction to the original charge it offsets.

    Both transactions must exist, must not be verified, and the refund must
    not substantially pre-date the original (1-day grace window). Currency
    must match. Account mismatch is allowed with a warning.

    Args:
        refund_txn_id: ID of the derived_transaction that is the refund.
        original_txn_id: ID of the derived_transaction being refunded.
    """

    def _run() -> dict[str, Any]:
        try:
            result = _record_refund(
                get_db(),
                refund_txn_id=refund_txn_id,
                original_txn_id=original_txn_id,
                matched_by="user",
            )
            response: dict[str, Any] = {
                "status": "success",
                "refund_txn_id": refund_txn_id,
                "original_txn_id": original_txn_id,
                "refund_amount_cents": result.refund_amount_cents,
                "original_amount_cents": result.original_amount_cents,
            }
            if result.warnings:
                response["warnings"] = result.warnings
            return response
        except RefundError as exc:
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)
