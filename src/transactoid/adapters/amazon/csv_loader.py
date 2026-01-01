"""Amazon CSV loaders for orders and items data."""

from __future__ import annotations

from collections.abc import Sequence
import csv
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


def _parse_cents(value: str) -> int:
    """Parse a currency string like '$39.27' into cents (3927)."""
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    return int(float(cleaned) * 100)


def _is_header_row(row: dict[str, str]) -> bool:
    """Check if row is a duplicate header (appears in concatenated exports)."""
    order_id = row.get("order id", "") or row.get("order_id", "")
    return order_id in ("order id", "order_id")


class AmazonOrdersCSVLoader:
    """Loads Amazon orders from CSV file."""

    REQUIRED_COLUMNS = {"date", "total"}
    ORDER_ID_COLUMNS = ("order id", "order_id")

    def __init__(self, csv_path: Path):
        """Initialize loader with path to orders CSV file."""
        self._csv_path = csv_path

    def load(self) -> dict[str, CSVOrder]:
        """Load orders from CSV file.

        Returns:
            Dict mapping order_id → CSVOrder
        """
        orders: dict[str, CSVOrder] = {}

        if not self._csv_path.exists():
            return orders

        with open(self._csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if not self._validate_columns(reader.fieldnames or []):
                return orders

            for row in reader:
                if _is_header_row(row):
                    continue

                order = self._parse_row(row)
                if order:
                    orders[order.order_id] = order

        return orders

    def _validate_columns(self, fieldnames: Sequence[str]) -> bool:
        """Validate CSV has required columns."""
        found = set(fieldnames)
        has_order_id = any(col in found for col in self.ORDER_ID_COLUMNS)
        missing = self.REQUIRED_COLUMNS - found

        return has_order_id and not missing

    def _parse_row(self, row: dict[str, str]) -> CSVOrder | None:
        """Parse a CSV row into a CSVOrder."""
        order_id = row.get("order id") or row.get("order_id", "")
        total_str = row.get("total", "")

        if not total_str.replace("$", "").replace(",", "").strip():
            return None

        return CSVOrder(
            order_id=order_id,
            order_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
            order_total_cents=_parse_cents(total_str),
            tax_cents=_parse_cents(row.get("tax", "")),
            shipping_cents=_parse_cents(row.get("shipping", "")),
        )


class AmazonItemsCSVLoader:
    """Loads Amazon items from CSV file."""

    REQUIRED_COLUMNS = {"description", "price", "quantity"}
    ORDER_ID_COLUMNS = ("order id", "order_id")
    ASIN_COLUMNS = ("ASIN", "asin")

    def __init__(self, csv_path: Path):
        """Initialize loader with path to items CSV file."""
        self._csv_path = csv_path

    def load(self) -> dict[str, list[CSVItem]]:
        """Load items from CSV file.

        Returns:
            Dict mapping order_id → list[CSVItem]
        """
        items_by_order: dict[str, list[CSVItem]] = {}

        if not self._csv_path.exists():
            return items_by_order

        with open(self._csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if not self._validate_columns(reader.fieldnames or []):
                return items_by_order

            for row in reader:
                if _is_header_row(row):
                    continue

                item = self._parse_row(row)
                if item:
                    if item.order_id not in items_by_order:
                        items_by_order[item.order_id] = []
                    items_by_order[item.order_id].append(item)

        return items_by_order

    def _validate_columns(self, fieldnames: Sequence[str]) -> bool:
        """Validate CSV has required columns."""
        found = set(fieldnames)
        has_order_id = any(col in found for col in self.ORDER_ID_COLUMNS)
        has_asin = any(col in found for col in self.ASIN_COLUMNS)
        missing = self.REQUIRED_COLUMNS - found

        return has_order_id and has_asin and not missing

    def _parse_row(self, row: dict[str, str]) -> CSVItem | None:
        """Parse a CSV row into a CSVItem."""
        order_id = row.get("order id") or row.get("order_id", "")
        asin = row.get("ASIN") or row.get("asin", "")

        return CSVItem(
            order_id=order_id,
            description=row["description"],
            price_cents=_parse_cents(row["price"]),
            quantity=int(row["quantity"]),
            asin=asin,
        )
