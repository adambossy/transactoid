"""Amazon CSV loader for orders and items data."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass
class CSVOrder:
    """Amazon order from CSV."""

    order_id: str
    order_date: date
    order_total_cents: int  # Total including tax + shipping
    tax_cents: int
    shipping_cents: int


@dataclass
class CSVItem:
    """Amazon item from CSV."""

    order_id: str
    description: str
    price_cents: int  # Price per SINGLE item, WITHOUT tax
    quantity: int  # Number of items
    asin: str  # Amazon product identifier


class AmazonCSVLoader:
    """Loads Amazon orders and items from CSV files."""

    def __init__(self, csv_dir: Path):
        """Initialize loader with CSV directory.

        Args:
            csv_dir: Directory containing amazon-order-history-*.csv files
        """
        self._csv_dir = csv_dir

    def load_orders_and_items(
        self,
    ) -> tuple[dict[str, CSVOrder], dict[str, list[CSVItem]]]:
        """Load orders and items from CSV files.

        Returns:
            Tuple of:
            - orders: dict mapping order_id → CSVOrder
            - items_by_order: dict mapping order_id → list[CSVItem]
        """
        orders: dict[str, CSVOrder] = {}
        items_by_order: dict[str, list[CSVItem]] = defaultdict(list)

        # Load orders
        orders_csv = self._csv_dir / "amazon-order-history-orders.csv"
        if orders_csv.exists():
            with open(orders_csv) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Parse total (e.g., "$39.27" → 3927 cents)
                    total_str = row["total"].replace("$", "").replace(",", "")
                    order_total_cents = int(float(total_str) * 100)

                    # Parse tax (may be empty)
                    tax_str = row.get("tax", "") or "0"
                    tax_cents = int(float(tax_str.replace("$", "").replace(",", "")) * 100)

                    # Parse shipping (may be empty)
                    shipping_str = row.get("shipping", "") or "0"
                    shipping_cents = int(
                        float(shipping_str.replace("$", "").replace(",", "")) * 100
                    )

                    orders[row["order_id"]] = CSVOrder(
                        order_id=row["order_id"],
                        order_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                        order_total_cents=order_total_cents,
                        tax_cents=tax_cents,
                        shipping_cents=shipping_cents,
                    )

        # Load items
        items_csv = self._csv_dir / "amazon-order-history-items.csv"
        if items_csv.exists():
            with open(items_csv) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Parse price (e.g., "$37.97" → 3797 cents)
                    price_str = row["price"].replace("$", "").replace(",", "")
                    price_cents = int(float(price_str) * 100)

                    # Parse quantity
                    quantity = int(row["quantity"])

                    items_by_order[row["order_id"]].append(
                        CSVItem(
                            order_id=row["order_id"],
                            description=row["description"],
                            price_cents=price_cents,
                            quantity=quantity,
                            asin=row["asin"],
                        )
                    )

        return orders, items_by_order
