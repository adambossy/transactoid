"""Amazon order index for O(1) lookup by amount."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from transactoid.adapters.amazon.csv_loader import (
    AmazonItem,
    AmazonItemsCSVLoader,
    AmazonOrder,
    AmazonOrdersCSVLoader,
)


class AmazonOrderIndex:
    """Index of Amazon orders for efficient lookup by amount.

    Provides O(1) lookup of orders by amount_cents using a hash map.
    """

    def __init__(
        self,
        orders: dict[str, AmazonOrder],
        items_by_order: dict[str, list[AmazonItem]],
    ) -> None:
        """Initialize with loaded orders and items.

        Args:
            orders: Dict mapping order_id -> AmazonOrder
            items_by_order: Dict mapping order_id -> list[AmazonItem]
        """
        self._orders = orders
        self._items_by_order = items_by_order
        self._by_amount: dict[int, list[AmazonOrder]] = defaultdict(list)

        # Build amount index for O(1) lookup
        for order in orders.values():
            self._by_amount[order.order_total_cents].append(order)

    @classmethod
    def from_csv_dir(cls, csv_dir: Path) -> AmazonOrderIndex:
        """Load index from CSV directory.

        Args:
            csv_dir: Directory containing Amazon CSV exports
                     (amazon-order-history-orders*.csv, amazon-order-history-items*.csv)

        Returns:
            AmazonOrderIndex populated from CSV files
        """
        orders = AmazonOrdersCSVLoader(csv_dir).load()
        items = AmazonItemsCSVLoader(csv_dir).load()
        return cls(orders, items)

    def get_orders_by_amount(self, amount_cents: int) -> list[AmazonOrder]:
        """Get all orders with the given amount. O(1) lookup.

        Args:
            amount_cents: Order total in cents

        Returns:
            List of orders with matching amount (may be empty)
        """
        return self._by_amount.get(amount_cents, [])

    def get_items(self, order_id: str) -> list[AmazonItem]:
        """Get items for an order.

        Args:
            order_id: Amazon order ID

        Returns:
            List of items in the order (may be empty)
        """
        return self._items_by_order.get(order_id, [])

    def get_order(self, order_id: str) -> AmazonOrder | None:
        """Get order by ID.

        Args:
            order_id: Amazon order ID

        Returns:
            AmazonOrder if found, None otherwise
        """
        return self._orders.get(order_id)

    @property
    def order_count(self) -> int:
        """Total number of orders in index."""
        return len(self._orders)

    @property
    def item_count(self) -> int:
        """Total number of items in index."""
        return sum(len(items) for items in self._items_by_order.values())
