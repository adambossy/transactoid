"""Tests for Amazon scraper Pydantic models."""

from __future__ import annotations

from transactoid.tools.amazon.scraper import (
    ScrapedItem,
    ScrapedOrder,
    ScrapeResult,
)


class TestScrapedItem:
    """Tests for ScrapedItem Pydantic model."""

    def test_scraped_item_creation(self) -> None:
        input_data = {
            "asin": "B0725BK81G",
            "description": "Gillette Mach3 Turbo Men's Razor",
            "price_cents": 3797,
            "quantity": 1,
        }

        item = ScrapedItem(**input_data)

        assert item.asin == input_data["asin"]
        assert item.description == input_data["description"]
        assert item.price_cents == input_data["price_cents"]
        assert item.quantity == input_data["quantity"]

    def test_scraped_item_serialization(self) -> None:
        item = ScrapedItem(
            asin="B0725BK81G",
            description="Test item",
            price_cents=1000,
            quantity=2,
        )

        serialized = item.model_dump()

        expected = {
            "asin": "B0725BK81G",
            "description": "Test item",
            "price_cents": 1000,
            "quantity": 2,
        }
        assert serialized == expected


class TestScrapedOrder:
    """Tests for ScrapedOrder Pydantic model."""

    def test_scraped_order_creation(self) -> None:
        input_data = {
            "order_id": "112-5793878-2607402",
            "order_date": "2024-01-15",
            "order_total_cents": 3927,
            "tax_cents": 320,
            "shipping_cents": 0,
            "items": [
                {
                    "asin": "B0725BK81G",
                    "description": "Test item",
                    "price_cents": 3797,
                    "quantity": 1,
                }
            ],
        }

        order = ScrapedOrder(**input_data)

        assert order.order_id == input_data["order_id"]
        assert order.order_date == input_data["order_date"]
        assert order.order_total_cents == input_data["order_total_cents"]
        assert order.tax_cents == input_data["tax_cents"]
        assert order.shipping_cents == input_data["shipping_cents"]
        assert len(order.items) == 1
        assert order.items[0].asin == "B0725BK81G"

    def test_scraped_order_with_multiple_items(self) -> None:
        order = ScrapedOrder(
            order_id="test-order",
            order_date="2024-01-15",
            order_total_cents=5000,
            tax_cents=400,
            shipping_cents=100,
            items=[
                ScrapedItem(
                    asin="ASIN1", description="Item 1", price_cents=2000, quantity=1
                ),
                ScrapedItem(
                    asin="ASIN2", description="Item 2", price_cents=2500, quantity=2
                ),
            ],
        )

        assert len(order.items) == 2
        assert order.items[0].asin == "ASIN1"
        assert order.items[1].asin == "ASIN2"


class TestScrapeResult:
    """Tests for ScrapeResult Pydantic model."""

    def test_scrape_result_creation(self) -> None:
        result = ScrapeResult(
            orders=[
                ScrapedOrder(
                    order_id="order-1",
                    order_date="2024-01-15",
                    order_total_cents=3927,
                    tax_cents=320,
                    shipping_cents=0,
                    items=[
                        ScrapedItem(
                            asin="ASIN1",
                            description="Item 1",
                            price_cents=3797,
                            quantity=1,
                        )
                    ],
                ),
                ScrapedOrder(
                    order_id="order-2",
                    order_date="2024-01-16",
                    order_total_cents=5000,
                    tax_cents=400,
                    shipping_cents=100,
                    items=[],
                ),
            ]
        )

        assert len(result.orders) == 2
        assert result.orders[0].order_id == "order-1"
        assert result.orders[1].order_id == "order-2"

    def test_scrape_result_empty_orders(self) -> None:
        result = ScrapeResult(orders=[])

        assert len(result.orders) == 0

    def test_scrape_result_serialization(self) -> None:
        result = ScrapeResult(
            orders=[
                ScrapedOrder(
                    order_id="test-order",
                    order_date="2024-01-15",
                    order_total_cents=1000,
                    tax_cents=100,
                    shipping_cents=50,
                    items=[],
                )
            ]
        )

        serialized = result.model_dump()

        expected = {
            "orders": [
                {
                    "order_id": "test-order",
                    "order_date": "2024-01-15",
                    "order_total_cents": 1000,
                    "tax_cents": 100,
                    "shipping_cents": 50,
                    "items": [],
                }
            ]
        }
        assert serialized == expected
