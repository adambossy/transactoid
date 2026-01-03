"""Tests for Amazon order to Plaid transaction matching."""

from datetime import date

from tests.adapters.amazon.fixtures import (
    EXPECTED_MATCHES,
    create_csv_orders,
    create_plaid_transactions,
)
from transactoid.adapters.amazon.csv_loader import CSVOrder
from transactoid.adapters.amazon.plaid_matcher import match_orders_to_transactions
from transactoid.adapters.db.models import PlaidTransaction


class TestMatchOrdersToTransactions:
    """Tests for the order matching algorithm."""

    def test_matches_all_orders_with_fixture_data(self) -> None:
        """All 25 fixture orders match their expected Plaid transactions."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == EXPECTED_MATCHES

    def test_exact_amount_match(self) -> None:
        """Orders match transactions with identical amounts."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {"ORDER-001": 1}

    def test_no_match_when_amount_differs(self) -> None:
        """Orders do not match transactions with different amounts."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),
                amount_cents=999,  # Different amount
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {"ORDER-001": None}

    def test_no_match_when_date_too_early(self) -> None:
        """Orders do not match transactions posted before order date."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 5),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 4),  # Before order date
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {"ORDER-001": None}

    def test_no_match_when_date_too_late(self) -> None:
        """Orders do not match transactions posted too long after order date."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 2, 1),  # 31 days later - beyond max_date_lag
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns, max_date_lag=30)

        # Assert
        assert matches == {"ORDER-001": None}

    def test_selects_closest_date_as_tiebreaker(self) -> None:
        """When multiple transactions have same amount, selects closest date."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 3),  # 2 days later
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
            PlaidTransaction(
                plaid_transaction_id=2,
                external_id="ext-2",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),  # 1 day later - closer
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert - should pick txn 2 (closer date)
        assert matches == {"ORDER-001": 2}

    def test_transaction_not_reused_for_multiple_orders(self) -> None:
        """Each transaction can only be matched to one order."""
        # Input - two orders with same amount
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
            CSVOrder(
                order_id="ORDER-002",
                order_date=date(2025, 1, 2),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        # Only one transaction with that amount
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert - first order gets the match, second order unmatched
        assert matches == {"ORDER-001": 1, "ORDER-002": None}

    def test_multiple_orders_match_different_transactions(self) -> None:
        """Multiple orders with same amount match different transactions."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
            CSVOrder(
                order_id="ORDER-002",
                order_date=date(2025, 1, 3),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),  # Closer to order 1
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
            PlaidTransaction(
                plaid_transaction_id=2,
                external_id="ext-2",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 4),  # Closer to order 2
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {"ORDER-001": 1, "ORDER-002": 2}

    def test_empty_orders_returns_empty_dict(self) -> None:
        """Empty order list returns empty match dict."""
        # Input
        orders: list[CSVOrder] = []
        plaid_txns = [
            PlaidTransaction(
                plaid_transaction_id=1,
                external_id="ext-1",
                source="PLAID",
                account_id="acc-1",
                posted_at=date(2025, 1, 2),
                amount_cents=1000,
                currency="USD",
                merchant_descriptor="Amazon",
                institution=None,
            ),
        ]

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {}

    def test_empty_transactions_returns_all_none(self) -> None:
        """Empty transaction list returns all orders unmatched."""
        # Input
        orders = [
            CSVOrder(
                order_id="ORDER-001",
                order_date=date(2025, 1, 1),
                order_total_cents=1000,
                tax_cents=100,
                shipping_cents=0,
            ),
        ]
        plaid_txns: list[PlaidTransaction] = []

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches == {"ORDER-001": None}


class TestIndividualFixtureMappings:
    """Safeguard tests verifying individual transaction-to-order mappings."""

    def test_order_1_single_item_hand_wash(self) -> None:
        """Order 113-5524816-2451403 ($150.25) maps to txn 839 - 1 item."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["113-5524816-2451403"] == 839

    def test_order_3_two_items_baby_wipes_and_diapers(self) -> None:
        """Order 113-2183381-7505026 ($49.77) maps to txn 841 - 2 items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["113-2183381-7505026"] == 841

    def test_order_6_small_amount_tripod_plate(self) -> None:
        """Order 112-7570534-9890666 ($7.61) maps to txn 831 - 1 item."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["112-7570534-9890666"] == 831

    def test_order_8_same_day_posting(self) -> None:
        """Order 112-4502156-7842663 ($40.47) maps to txn 771 - 0-day lag."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["112-4502156-7842663"] == 771

    def test_order_11_three_items_baby_clothes(self) -> None:
        """Order 113-8425491-4935405 ($45.30) maps to txn 791 - 3 items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["113-8425491-4935405"] == 791

    def test_order_17_probiotic_drops(self) -> None:
        """Order 112-9348880-7178650 ($49.98) maps to txn 27 - 1 item."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["112-9348880-7178650"] == 27

    def test_order_21_duplicate_items_same_asin(self) -> None:
        """Order 112-9508317-5020242 ($10.98) maps to txn 189 - 2 same items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["112-9508317-5020242"] == 189

    def test_order_22_four_items_with_duplicates(self) -> None:
        """Order 112-9053665-8377064 ($59.24) maps to txn 198 - 4 items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["112-9053665-8377064"] == 198

    def test_order_24_two_baby_bottles(self) -> None:
        """Order 113-1031800-1734626 ($8.69) maps to txn 203 - 2 same items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["113-1031800-1734626"] == 203

    def test_order_25_large_order_airpods(self) -> None:
        """Order 113-3910520-0532212 ($207.92) maps to txn 202 - 3 items."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Assert
        assert matches["113-3910520-0532212"] == 202


class TestMatchRateMetrics:
    """Tests for match rate calculations on fixture data."""

    def test_fixture_match_rate_is_100_percent(self) -> None:
        """Fixture data achieves 100% match rate."""
        # Input
        orders = create_csv_orders()
        plaid_txns = create_plaid_transactions()

        # Act
        matches = match_orders_to_transactions(orders, plaid_txns)

        # Calculate match rate
        matched_count = sum(1 for v in matches.values() if v is not None)
        total_count = len(matches)
        match_rate = matched_count / total_count if total_count > 0 else 0.0

        # Assert
        assert match_rate == 1.0
        assert matched_count == 25
