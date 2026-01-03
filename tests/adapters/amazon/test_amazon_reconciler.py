"""Tests for Amazon reconciliation logic."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from transactoid.adapters.amazon.amazon_reconciler import (
    AmazonReconcilerLogger,
    OrderAmountIndex,
    find_matching_amazon_order,
)
from transactoid.adapters.amazon.csv_loader import CSVOrder
from transactoid.adapters.db.models import PlaidTransaction


def create_plaid_txn(
    plaid_transaction_id: int,
    external_id: str,
    amount_cents: int,
    posted_at: date,
) -> PlaidTransaction:
    """Create a PlaidTransaction for testing."""
    txn = PlaidTransaction()
    txn.plaid_transaction_id = plaid_transaction_id
    txn.external_id = external_id
    txn.amount_cents = amount_cents
    txn.posted_at = posted_at
    txn.merchant_descriptor = "Amazon"
    return txn


def create_csv_order(
    order_id: str,
    order_total_cents: int,
    order_date: date,
    tax_cents: int = 0,
    shipping_cents: int = 0,
) -> CSVOrder:
    """Create a CSVOrder for testing."""
    return CSVOrder(
        order_id=order_id,
        order_date=order_date,
        order_total_cents=order_total_cents,
        tax_cents=tax_cents,
        shipping_cents=shipping_cents,
    )


class TestFindMatchingAmazonOrder:
    """Tests for find_matching_amazon_order function."""

    def test_finds_exact_match(self) -> None:
        # Input
        order = create_csv_order("order-1", 5000, date(2024, 1, 15))
        plaid_txn = create_plaid_txn(1, "ext-1", -5000, date(2024, 1, 15))

        # Setup
        order_index = OrderAmountIndex({"order-1": order})
        mock_logger = MagicMock(spec=AmazonReconcilerLogger)

        # Act
        result = find_matching_amazon_order(
            plaid_txn, order_index, reconciler_logger=mock_logger
        )

        # Assert
        assert result == order

    def test_finds_match_within_tolerance(self) -> None:
        # Input - order $50.30, transaction $50.00 (30 cents diff)
        order = create_csv_order("order-1", 5030, date(2024, 1, 15))
        plaid_txn = create_plaid_txn(1, "ext-1", -5000, date(2024, 1, 16))

        # Setup
        order_index = OrderAmountIndex({"order-1": order})
        mock_logger = MagicMock(spec=AmazonReconcilerLogger)

        # Act
        result = find_matching_amazon_order(
            plaid_txn, order_index, reconciler_logger=mock_logger
        )

        # Assert
        assert result == order

    def test_returns_none_when_no_match(self) -> None:
        # Input - order $100, transaction $50 (way off)
        order = create_csv_order("order-1", 10000, date(2024, 1, 15))
        plaid_txn = create_plaid_txn(1, "ext-1", -5000, date(2024, 1, 15))

        # Setup
        order_index = OrderAmountIndex({"order-1": order})
        mock_logger = MagicMock(spec=AmazonReconcilerLogger)

        # Act
        result = find_matching_amazon_order(
            plaid_txn, order_index, reconciler_logger=mock_logger
        )

        # Assert
        assert result is None

    def test_skip_near_miss_scan_skips_expensive_logging(self) -> None:
        # Input - no match scenario
        order = create_csv_order("order-1", 10000, date(2024, 1, 15))
        plaid_txn = create_plaid_txn(1, "ext-1", -5000, date(2024, 1, 15))

        # Setup
        order_index = OrderAmountIndex({"order-1": order})
        mock_logger = MagicMock(spec=AmazonReconcilerLogger)

        # Act
        result = find_matching_amazon_order(
            plaid_txn,
            order_index,
            skip_near_miss_scan=True,
            reconciler_logger=mock_logger,
        )

        # Assert - result is None and near-miss logging was NOT called
        assert result is None
        mock_logger.near_misses_found.assert_not_called()
        mock_logger.no_near_misses.assert_not_called()

    def test_near_miss_scan_enabled_by_default(self) -> None:
        # Input - no match scenario with close order for near-miss detection
        # Order has close amount but date outside 30-day tolerance (triggers near-miss)
        order = create_csv_order("order-1", 5500, date(2024, 3, 1))
        plaid_txn = create_plaid_txn(1, "ext-1", -5000, date(2024, 1, 15))

        # Setup
        order_index = OrderAmountIndex({"order-1": order})
        mock_logger = MagicMock(spec=AmazonReconcilerLogger)

        # Act - skip_near_miss_scan defaults to False
        result = find_matching_amazon_order(
            plaid_txn,
            order_index,
            reconciler_logger=mock_logger,
        )

        # Assert - near-miss logging WAS called
        assert result is None
        assert mock_logger.near_misses_found.called or mock_logger.no_near_misses.called


class TestOrderAmountIndex:
    """Tests for OrderAmountIndex class."""

    def test_get_candidates_returns_orders_in_tolerance(self) -> None:
        # Input
        orders = {
            "order-1": create_csv_order("order-1", 4900, date(2024, 1, 15)),  # $49.00
            "order-2": create_csv_order("order-2", 5050, date(2024, 1, 15)),  # $50.50
            "order-3": create_csv_order("order-3", 10000, date(2024, 1, 15)),  # $100.00
        }

        # Setup
        index = OrderAmountIndex(orders)

        # Act - search for $50.00 with 50 cent tolerance
        candidates = index.get_candidates(5000, 50)

        # Assert - should find order-1 and order-2, not order-3
        candidate_ids = {c.order_id for c in candidates}
        assert "order-1" in candidate_ids
        assert "order-2" in candidate_ids
        assert "order-3" not in candidate_ids

    def test_len_returns_total_orders(self) -> None:
        # Input
        orders = {
            "order-1": create_csv_order("order-1", 5000, date(2024, 1, 15)),
            "order-2": create_csv_order("order-2", 6000, date(2024, 1, 16)),
        }

        # Setup
        index = OrderAmountIndex(orders)

        # Assert
        assert len(index) == 2
