"""Amazon domain entities used by matching and splitting logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AmazonOrder:
    """Amazon order data used by reconciliation logic."""

    order_id: str
    order_date: date
    order_total_cents: int
    tax_cents: int
    shipping_cents: int


@dataclass
class AmazonItem:
    """Amazon item data used by splitting logic."""

    order_id: str
    description: str
    price_cents: int
    quantity: int
    asin: str
