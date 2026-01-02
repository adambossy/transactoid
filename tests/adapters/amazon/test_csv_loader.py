"""Tests for Amazon CSV loaders using real CSV files."""

from __future__ import annotations

from pathlib import Path

import pytest

from transactoid.adapters.amazon.csv_loader import (
    AmazonItemsCSVLoader,
    AmazonOrdersCSVLoader,
    CSVItem,
    CSVOrder,
)

# Path to the Amazon CSV directory
# test_csv_loader.py -> amazon -> adapters -> tests -> amazon-splitting
AMAZON_CSV_DIR = Path(__file__).parents[3] / ".transactions" / "amazon"


class TestAmazonOrdersCSVLoader:
    """Tests for AmazonOrdersCSVLoader."""

    @pytest.fixture
    def loader(self) -> AmazonOrdersCSVLoader:
        return AmazonOrdersCSVLoader(AMAZON_CSV_DIR)

    def test_orders_csv_exists(self) -> None:
        orders_files = list(AMAZON_CSV_DIR.glob("amazon-order-history-orders*.csv"))
        assert len(orders_files) > 0, f"No orders CSVs found in: {AMAZON_CSV_DIR}"

    def test_load_returns_non_empty_dict(self, loader: AmazonOrdersCSVLoader) -> None:
        orders = loader.load()

        assert len(orders) > 0

    def test_orders_have_expected_fields(self, loader: AmazonOrdersCSVLoader) -> None:
        orders = loader.load()

        for order_id, order in orders.items():
            assert isinstance(order, CSVOrder)
            assert order.order_id == order_id
            assert order.order_date is not None
            assert order.order_total_cents >= 0
            assert order.tax_cents >= 0
            assert order.shipping_cents >= 0

    def test_specific_known_order_loaded(self, loader: AmazonOrdersCSVLoader) -> None:
        """Verify order 112-5793878-2607402: Gillette Mach3, $39.27 total."""
        orders = loader.load()

        known_order_id = "112-5793878-2607402"

        assert known_order_id in orders
        order = orders[known_order_id]
        assert order.order_total_cents == 3927  # $39.27
        assert order.tax_cents == 320  # $3.20
        assert order.shipping_cents == 0

    def test_missing_dir_returns_empty_dict(self, tmp_path: Path) -> None:
        loader = AmazonOrdersCSVLoader(tmp_path / "nonexistent")

        orders = loader.load()

        assert orders == {}


class TestAmazonItemsCSVLoader:
    """Tests for AmazonItemsCSVLoader."""

    @pytest.fixture
    def loader(self) -> AmazonItemsCSVLoader:
        return AmazonItemsCSVLoader(AMAZON_CSV_DIR)

    def test_items_csv_exists(self) -> None:
        items_files = list(AMAZON_CSV_DIR.glob("amazon-order-history-items*.csv"))
        assert len(items_files) > 0, f"No items CSVs found in: {AMAZON_CSV_DIR}"

    def test_load_returns_non_empty_dict(self, loader: AmazonItemsCSVLoader) -> None:
        items_by_order = loader.load()

        total_items = sum(len(items) for items in items_by_order.values())
        assert total_items > 0

    def test_items_have_expected_fields(self, loader: AmazonItemsCSVLoader) -> None:
        items_by_order = loader.load()

        for order_id, items in items_by_order.items():
            for item in items:
                assert isinstance(item, CSVItem)
                assert item.order_id == order_id
                assert item.description != ""
                assert item.price_cents >= 0
                assert item.quantity >= 1
                assert item.asin != ""

    def test_specific_known_item_loaded(self, loader: AmazonItemsCSVLoader) -> None:
        """Verify item from order 112-5793878-2607402: Gillette Mach3."""
        items_by_order = loader.load()

        known_order_id = "112-5793878-2607402"

        assert known_order_id in items_by_order
        items = items_by_order[known_order_id]
        assert len(items) == 1

        item = items[0]
        assert "Gillette" in item.description
        assert item.price_cents == 3797  # $37.97
        assert item.quantity == 1
        assert item.asin == "B0725BK81G"

    def test_missing_dir_returns_empty_dict(self, tmp_path: Path) -> None:
        loader = AmazonItemsCSVLoader(tmp_path / "nonexistent")

        items = loader.load()

        assert items == {}


class TestLoadersIntegration:
    """Tests that verify orders and items can be linked together."""

    def test_items_linked_to_orders(self) -> None:
        orders = AmazonOrdersCSVLoader(AMAZON_CSV_DIR).load()
        items_by_order = AmazonItemsCSVLoader(AMAZON_CSV_DIR).load()

        matched_count = sum(1 for order_id in items_by_order if order_id in orders)

        assert matched_count > 0
