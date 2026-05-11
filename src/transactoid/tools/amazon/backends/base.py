"""Base protocol for Amazon scraper backends."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from transactoid.tools.amazon.scraper import ScrapedOrder


class AmazonScraperBackend(Protocol):
    """Protocol for Amazon scraper backends.

    All backends must implement scrape_order_history to return a list of
    ScrapedOrder objects. The main scraper tool handles database persistence.

    Year-by-year navigation, when needed, is the implementation's concern.
    Callers pass only the date window (since/until) plus an optional cap.
    """

    def scrape_order_history(
        self,
        *,
        since: date | None = None,
        until: date | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history within an inclusive date window.

        Args:
            since: Inclusive lower bound on ``order_date``. ``None`` means no
                lower bound. Already DB-floored by the orchestrator before it
                reaches the backend.
            until: Inclusive upper bound on ``order_date``. ``None`` means no
                upper bound.
            max_orders: Optional maximum number of orders to scrape across all
                pages/years. ``None`` means scrape everything that matches.

        Returns:
            List of ScrapedOrder objects with order details and items.
        """
        ...
