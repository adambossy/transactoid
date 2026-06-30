"""Light tests for the split_transaction and record_refund agent tools.

Verifies success and error dict shapes without exercising the full DB layer.
The @tool decorator wraps functions in a Tool dataclass; call .fn() directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from penny.tools.transactions import (
    hide_transactions,
    record_refund,
    split_transaction,
    unhide_transactions,
)

# ---------------------------------------------------------------------------
# split_transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_transaction_success_shape() -> None:
    """Success response includes status, new_transaction_ids, and parts."""
    new_ids = [101, 102]
    with patch("penny.tools.transactions._split_transaction", return_value=new_ids):
        result = await split_transaction.fn(txn_id=1, amounts=[30.00, 20.00])

    assert result["status"] == "success"
    assert result["new_transaction_ids"] == [101, 102]
    parts = result["parts"]
    assert isinstance(parts, list)
    assert len(parts) == 2
    assert parts[0] == {"transaction_id": 101, "amount_cents": 3000}
    assert parts[1] == {"transaction_id": 102, "amount_cents": 2000}


@pytest.mark.asyncio
async def test_split_transaction_service_error_shape() -> None:
    """Service SplitError surfaces as status=error with message."""
    from penny.errors import SplitError

    with patch(
        "penny.tools.transactions._split_transaction",
        side_effect=SplitError("transaction 99 not found"),
    ):
        result = await split_transaction.fn(txn_id=99, amounts=[30.00, 20.00])

    assert result["status"] == "error"
    assert "transaction 99 not found" in result["message"]


@pytest.mark.asyncio
async def test_split_transaction_invalid_amount_zero() -> None:
    """Zero amount is rejected before calling the service."""
    result = await split_transaction.fn(txn_id=1, amounts=[50.00, 0.00])

    assert result["status"] == "error"
    assert "positive" in result["message"]


@pytest.mark.asyncio
async def test_split_transaction_invalid_amount_negative() -> None:
    """Negative amount is rejected before calling the service."""
    result = await split_transaction.fn(txn_id=1, amounts=[60.00, -10.00])

    assert result["status"] == "error"
    assert "positive" in result["message"]


@pytest.mark.asyncio
async def test_split_transaction_invalid_too_many_decimals() -> None:
    """More than 2 decimal places is rejected before calling the service."""
    result = await split_transaction.fn(txn_id=1, amounts=[30.001, 20.00])

    assert result["status"] == "error"
    assert "decimal" in result["message"]


# ---------------------------------------------------------------------------
# record_refund
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_refund_success_shape() -> None:
    """Success response includes status, txn IDs, and amount_cents fields."""
    from penny.tools._services.refund import RefundResult

    mock_result = RefundResult(
        refund_amount_cents=-1000,
        original_amount_cents=5000,
        warnings=[],
    )
    with patch("penny.tools.transactions._record_refund", return_value=mock_result):
        result = await record_refund.fn(refund_txn_id=2, original_txn_id=1)

    assert result["status"] == "success"
    assert result["refund_txn_id"] == 2
    assert result["original_txn_id"] == 1
    assert result["refund_amount_cents"] == -1000
    assert result["original_amount_cents"] == 5000
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_record_refund_success_with_warnings() -> None:
    """Warnings from RefundResult are included in the response."""
    from penny.tools._services.refund import RefundResult

    mock_result = RefundResult(
        refund_amount_cents=-500,
        original_amount_cents=5000,
        warnings=["Refund TXN-2 and original TXN-1 are on different accounts"],
    )
    with patch("penny.tools.transactions._record_refund", return_value=mock_result):
        result = await record_refund.fn(refund_txn_id=2, original_txn_id=1)

    assert result["status"] == "success"
    assert len(result["warnings"]) == 1


@pytest.mark.asyncio
async def test_record_refund_service_error_shape() -> None:
    """Service RefundError surfaces as status=error with message."""
    from penny.errors import RefundError

    with patch(
        "penny.tools.transactions._record_refund",
        side_effect=RefundError("transaction 99 not found"),
    ):
        result = await record_refund.fn(refund_txn_id=99, original_txn_id=1)

    assert result["status"] == "error"
    assert "transaction 99 not found" in result["message"]


# ---------------------------------------------------------------------------
# hide_transactions / unhide_transactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hide_transactions_success_shape() -> None:
    """hide_transactions reports the updated count and a 'Hid' message."""
    persister = MagicMock()
    persister.set_transactions_visibility.return_value = 2
    with patch("penny.tools.transactions.get_persister", return_value=persister):
        result = await hide_transactions.fn(transaction_ids=[1, 2])

    persister.set_transactions_visibility.assert_called_once_with([1, 2], False)
    assert result["status"] == "success"
    assert result["updated"] == 2
    assert "Hid 2" in result["message"]


@pytest.mark.asyncio
async def test_unhide_transactions_success_shape() -> None:
    """unhide_transactions calls the service with visible=True."""
    persister = MagicMock()
    persister.set_transactions_visibility.return_value = 1
    with patch("penny.tools.transactions.get_persister", return_value=persister):
        result = await unhide_transactions.fn(transaction_ids=[1])

    persister.set_transactions_visibility.assert_called_once_with([1], True)
    assert result["status"] == "success"
    assert result["updated"] == 1
    assert "Unhid 1" in result["message"]


@pytest.mark.asyncio
async def test_hide_transactions_service_error_shape() -> None:
    """A service exception surfaces as status=error with updated=0."""
    persister = MagicMock()
    persister.set_transactions_visibility.side_effect = RuntimeError("db down")
    with patch("penny.tools.transactions.get_persister", return_value=persister):
        result = await hide_transactions.fn(transaction_ids=[1])

    assert result["status"] == "error"
    assert result["updated"] == 0
    assert "db down" in result["message"]
