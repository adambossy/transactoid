"""Tests for Amazon order and item database models and facade methods."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TypedDict

from transactoid.adapters.db.facade import DB


class AmazonOrderInput(TypedDict):
    order_id: str
    order_date: date
    order_total_cents: int
    tax_cents: int
    shipping_cents: int


class AmazonItemInput(TypedDict):
    order_id: str
    asin: str
    description: str
    price_cents: int
    quantity: int


def create_db(tmp_path: Path) -> DB:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


class TestAmazonOrderDB:
    """Tests for AmazonOrderDB model and upsert methods."""

    def test_upsert_amazon_order_creates_new_order(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        input_data: AmazonOrderInput = {
            "order_id": "112-5793878-2607402",
            "order_date": date(2024, 1, 15),
            "order_total_cents": 3927,
            "tax_cents": 320,
            "shipping_cents": 0,
        }

        order = db.upsert_amazon_order(**input_data)

        assert order.order_id == input_data["order_id"]
        assert order.order_date == input_data["order_date"]
        assert order.order_total_cents == input_data["order_total_cents"]
        assert order.tax_cents == input_data["tax_cents"]
        assert order.shipping_cents == input_data["shipping_cents"]

    def test_upsert_amazon_order_updates_existing_order(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=3927,
            tax_cents=320,
            shipping_cents=0,
        )

        updated_order = db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 16),
            order_total_cents=4500,
            tax_cents=400,
            shipping_cents=100,
        )

        assert updated_order.order_id == order_id
        assert updated_order.order_date == date(2024, 1, 16)
        assert updated_order.order_total_cents == 4500
        assert updated_order.tax_cents == 400
        assert updated_order.shipping_cents == 100

    def test_get_amazon_order_returns_order(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=3927,
            tax_cents=320,
            shipping_cents=0,
        )

        order = db.get_amazon_order(order_id)

        assert order is not None
        assert order.order_id == order_id

    def test_get_amazon_order_returns_none_for_missing(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order = db.get_amazon_order("nonexistent-order")

        assert order is None

    def test_list_amazon_orders_returns_all_orders(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        db.upsert_amazon_order(
            order_id="order-1",
            order_date=date(2024, 1, 15),
            order_total_cents=1000,
        )
        db.upsert_amazon_order(
            order_id="order-2",
            order_date=date(2024, 1, 16),
            order_total_cents=2000,
        )

        orders = db.list_amazon_orders()

        assert len(orders) == 2
        order_ids = {o.order_id for o in orders}
        assert order_ids == {"order-1", "order-2"}


class TestAmazonItemDB:
    """Tests for AmazonItemDB model and upsert methods."""

    def test_upsert_amazon_item_creates_new_item(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        db.upsert_amazon_order(
            order_id="112-5793878-2607402",
            order_date=date(2024, 1, 15),
            order_total_cents=3927,
        )
        input_data: AmazonItemInput = {
            "order_id": "112-5793878-2607402",
            "asin": "B0725BK81G",
            "description": "Gillette Mach3 Turbo Men's Razor Blade Refill Cartridges",
            "price_cents": 3797,
            "quantity": 1,
        }

        item = db.upsert_amazon_item(**input_data)

        assert item.order_id == input_data["order_id"]
        assert item.asin == input_data["asin"]
        assert item.description == input_data["description"]
        assert item.price_cents == input_data["price_cents"]
        assert item.quantity == input_data["quantity"]

    def test_upsert_amazon_item_updates_existing_item(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        asin = "B0725BK81G"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=3927,
        )
        db.upsert_amazon_item(
            order_id=order_id,
            asin=asin,
            description="Original description",
            price_cents=3797,
            quantity=1,
        )

        updated_item = db.upsert_amazon_item(
            order_id=order_id,
            asin=asin,
            description="Updated description",
            price_cents=4000,
            quantity=2,
        )

        assert updated_item.order_id == order_id
        assert updated_item.asin == asin
        assert updated_item.description == "Updated description"
        assert updated_item.price_cents == 4000
        assert updated_item.quantity == 2

    def test_get_amazon_items_for_order_returns_items(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=5000,
        )
        db.upsert_amazon_item(
            order_id=order_id,
            asin="ASIN1",
            description="Item 1",
            price_cents=2000,
        )
        db.upsert_amazon_item(
            order_id=order_id,
            asin="ASIN2",
            description="Item 2",
            price_cents=3000,
        )

        items = db.get_amazon_items_for_order(order_id)

        assert len(items) == 2
        asins = {i.asin for i in items}
        assert asins == {"ASIN1", "ASIN2"}

    def test_get_amazon_items_for_order_returns_empty_for_no_items(
        self, tmp_path: Path
    ) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=1000,
        )

        items = db.get_amazon_items_for_order(order_id)

        assert items == []

    def test_unique_constraint_order_asin(self, tmp_path: Path) -> None:
        db = create_db(tmp_path)
        order_id = "112-5793878-2607402"
        db.upsert_amazon_order(
            order_id=order_id,
            order_date=date(2024, 1, 15),
            order_total_cents=3927,
        )
        db.upsert_amazon_item(
            order_id=order_id,
            asin="SAME-ASIN",
            description="First item",
            price_cents=1000,
        )

        db.upsert_amazon_item(
            order_id=order_id,
            asin="SAME-ASIN",
            description="Updated item",
            price_cents=2000,
        )

        items = db.get_amazon_items_for_order(order_id)
        assert len(items) == 1
        assert items[0].description == "Updated item"
