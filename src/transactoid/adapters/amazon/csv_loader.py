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


def _parse_cents(value: str) -> int | None:
    """Parse a currency string like '$39.27' into cents (3927).

    Returns None if the value cannot be parsed.
    """
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return int(float(cleaned) * 100)
    except ValueError:
        return None


def _is_header_row(row: dict[str, str]) -> bool:
    """Check if row is a duplicate header (appears in concatenated exports)."""
    order_id = row.get("order id", "") or row.get("order_id", "")
    return order_id in ("order id", "order_id")


class AmazonOrdersCSVLoader:
    """Loads Amazon orders from CSV files."""

    REQUIRED_COLUMNS = {"date", "total"}
    ORDER_ID_COLUMNS = ("order id", "order_id")
    FILE_PREFIX = "amazon-order-history-orders"

    def __init__(self, csv_dir: Path):
        """Initialize loader with directory containing orders CSV files."""
        self._csv_dir = csv_dir

    def load(self) -> dict[str, CSVOrder]:
        """Load orders from all matching CSV files.

        Returns:
            Dict mapping order_id → CSVOrder
        """
        orders: dict[str, CSVOrder] = {}

        if not self._csv_dir.exists():
            return orders

        for csv_path in sorted(self._csv_dir.glob(f"{self.FILE_PREFIX}*.csv")):
            self._load_file(csv_path, orders)

        return orders

    def _load_file(self, csv_path: Path, orders: dict[str, CSVOrder]) -> None:
        """Load orders from a single CSV file into the orders dict."""
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if not self._validate_columns(reader.fieldnames or []):
                return

            for row in reader:
                if _is_header_row(row):
                    continue

                order = self._parse_row(row)
                if order:
                    orders[order.order_id] = order

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

        total_cents = _parse_cents(total_str)
        if total_cents is None:
            return None

        tax_cents = _parse_cents(row.get("tax", ""))
        shipping_cents = _parse_cents(row.get("shipping", ""))

        return CSVOrder(
            order_id=order_id,
            order_date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
            order_total_cents=total_cents,
            tax_cents=tax_cents if tax_cents is not None else 0,
            shipping_cents=shipping_cents if shipping_cents is not None else 0,
        )


class AmazonItemsCSVLoader:
    """Loads Amazon items from CSV files."""

    REQUIRED_COLUMNS = {"description", "price", "quantity"}
    ORDER_ID_COLUMNS = ("order id", "order_id")
    ASIN_COLUMNS = ("ASIN", "asin")
    FILE_PREFIX = "amazon-order-history-items"

    def __init__(self, csv_dir: Path):
        """Initialize loader with directory containing items CSV files."""
        self._csv_dir = csv_dir

    def load(self) -> dict[str, list[CSVItem]]:
        """Load items from all matching CSV files.

        Returns:
            Dict mapping order_id → list[CSVItem]
        """
        items_by_order: dict[str, list[CSVItem]] = {}

        if not self._csv_dir.exists():
            return items_by_order

        for csv_path in sorted(self._csv_dir.glob(f"{self.FILE_PREFIX}*.csv")):
            self._load_file(csv_path, items_by_order)

        return items_by_order

    def _load_file(
        self, csv_path: Path, items_by_order: dict[str, list[CSVItem]]
    ) -> None:
        """Load items from a single CSV file into the items dict."""
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if not self._validate_columns(reader.fieldnames or []):
                return

            for row in reader:
                if _is_header_row(row):
                    continue

                item = self._parse_row(row)
                if item:
                    if item.order_id not in items_by_order:
                        items_by_order[item.order_id] = []
                    items_by_order[item.order_id].append(item)

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
        quantity_str = row.get("quantity", "").strip()

        # Skip rows with missing required data
        if not quantity_str or not asin:
            return None

        price_cents = _parse_cents(row.get("price", ""))
        if price_cents is None:
            return None

        return CSVItem(
            order_id=order_id,
            description=row["description"],
            price_cents=price_cents,
            quantity=int(quantity_str),
            asin=asin,
        )
