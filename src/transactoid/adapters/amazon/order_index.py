"""Amazon order index for efficient order and item lookup."""

from __future__ import annotations

from transactoid.adapters.amazon.entities import AmazonItem, AmazonOrder
from transactoid.adapters.db.facade import DB


class AmazonOrderIndex:
    """Index of Amazon orders and items for efficient lookup."""

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

    @classmethod
    def from_db(cls, db: DB) -> AmazonOrderIndex:
        """Load index from persisted Amazon order/item tables.

        Args:
            db: Database facade used to read Amazon orders and items.

        Returns:
            AmazonOrderIndex populated from database rows.
        """
        orders_by_id: dict[str, AmazonOrder] = {}
        items_by_order: dict[str, list[AmazonItem]] = {}

        for order in db.list_amazon_orders():
            orders_by_id[order.order_id] = AmazonOrder(
                order_id=order.order_id,
                order_date=order.order_date,
                order_total_cents=order.order_total_cents,
                tax_cents=order.tax_cents,
                shipping_cents=order.shipping_cents,
            )
            raw_items = db.get_amazon_items_for_order(order.order_id)
            if raw_items:
                items_by_order[order.order_id] = [
                    AmazonItem(
                        order_id=item.order_id,
                        asin=item.asin,
                        description=item.description,
                        price_cents=item.price_cents,
                        quantity=item.quantity,
                    )
                    for item in raw_items
                ]

        orders = orders_by_id
        items = items_by_order
        return cls(orders, items)

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

    def list_orders(self) -> list[AmazonOrder]:
        """Get all indexed orders."""
        return list(self._orders.values())

    @property
    def order_count(self) -> int:
        """Total number of orders in index."""
        return len(self._orders)

    @property
    def item_count(self) -> int:
        """Total number of items in index."""
        return sum(len(items) for items in self._items_by_order.values())
