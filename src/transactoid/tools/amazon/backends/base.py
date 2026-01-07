"""Base protocol for Amazon scraper backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from transactoid.tools.amazon.scraper import ScrapedOrder


class AmazonScraperBackend(Protocol):
    """Protocol for Amazon scraper backends.

    All backends must implement scrape_order_history to return a list of
    ScrapedOrder objects. The main scraper tool handles database persistence.
    """

    def scrape_order_history(
        self,
        year: int | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history.

        Args:
            year: Optional year to filter orders (e.g., 2024). If None, scrapes
                the most recent year.
            max_orders: Optional maximum number of orders to scrape. If None,
                scrapes all available orders.

        Returns:
            List of ScrapedOrder objects with order details and items.
        """
        ...
