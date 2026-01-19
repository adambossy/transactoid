"""Amazon order scraper with multiple browser backend support."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB
    from transactoid.tools.amazon.backends.base import AmazonScraperBackend


class ScrapedItem(BaseModel):
    """A single item scraped from an Amazon order."""

    asin: str
    description: str
    price_cents: int
    quantity: int


class ScrapedOrder(BaseModel):
    """A single Amazon order scraped from order history."""

    order_id: str
    order_date: str  # YYYY-MM-DD format
    order_total_cents: int
    tax_cents: int
    shipping_cents: int
    items: list[ScrapedItem]


class ScrapeResult(BaseModel):
    """Result of scraping Amazon orders."""

    orders: list[ScrapedOrder]


BackendType = Literal["playwriter", "stagehand", "stagehand-browserbase"]


def _get_backend(
    backend: BackendType,
    *,
    context_id: str | None = None,
    login_mode: bool = False,
) -> AmazonScraperBackend:
    """Get the backend instance for the specified type.

    Args:
        backend: Backend type to use.
        context_id: Optional Browserbase context ID for session persistence.
            Only applicable for "stagehand-browserbase" backend.
        login_mode: If True, wait for manual login via Session Live View.
            Only applicable for "stagehand-browserbase" backend.

    Returns:
        Backend instance implementing AmazonScraperBackend protocol.

    Raises:
        ValueError: If backend type is not supported.
    """
    if backend == "playwriter":
        from transactoid.tools.amazon.backends.playwriter import PlaywriterBackend

        return PlaywriterBackend()
    elif backend == "stagehand":
        from transactoid.tools.amazon.backends.stagehand_local import (
            StagehandLocalBackend,
        )

        return StagehandLocalBackend()
    elif backend == "stagehand-browserbase":
        from transactoid.tools.amazon.backends.stagehand_browserbase import (
            StagehandBrowserbaseBackend,
        )

        return StagehandBrowserbaseBackend(context_id=context_id, login_mode=login_mode)
    else:
        raise ValueError(f"Unsupported backend: {backend}")


def _persist_orders(db: DB, orders: list[ScrapedOrder]) -> dict[str, int]:
    """Persist scraped orders to database.

    Args:
        db: Database facade for persisting data.
        orders: List of scraped orders to persist.

    Returns:
        Dictionary with orders_created and items_created counts.
    """
    orders_created = 0
    items_created = 0

    for order in orders:
        db.upsert_amazon_order(
            order_id=order.order_id,
            order_date=date.fromisoformat(order.order_date),
            order_total_cents=order.order_total_cents,
            tax_cents=order.tax_cents,
            shipping_cents=order.shipping_cents,
        )
        orders_created += 1

        for item in order.items:
            db.upsert_amazon_item(
                order_id=order.order_id,
                asin=item.asin,
                description=item.description,
                price_cents=item.price_cents,
                quantity=item.quantity,
            )
            items_created += 1

    return {"orders_created": orders_created, "items_created": items_created}


def scrape_amazon_orders(
    db: DB,
    backend: BackendType = "playwriter",
    year: int | None = None,
    max_orders: int | None = None,
    context_id: str | None = None,
    login_mode: bool = False,
) -> dict[str, Any]:
    """Scrape Amazon orders using the specified backend.

    Args:
        db: Database facade for persisting scraped data.
        backend: Browser backend to use ("playwriter", "stagehand", or
            "stagehand-browserbase").
        year: Optional year to filter orders (e.g., 2024).
        max_orders: Optional maximum number of orders to scrape.
        context_id: Optional Browserbase context ID for session persistence.
            Only applicable for "stagehand-browserbase" backend. Use
            StagehandBrowserbaseBackend.create_context() to create one.
        login_mode: If True, wait for manual login via Session Live View.
            Only applicable for "stagehand-browserbase" backend.

    Returns:
        Dictionary with status and summary of scraped data.
    """
    backend_instance = _get_backend(
        backend, context_id=context_id, login_mode=login_mode
    )
    orders = backend_instance.scrape_order_history(year=year, max_orders=max_orders)

    if not orders:
        return {
            "status": "error",
            "message": "Scraper did not return any results",
            "orders_created": 0,
            "items_created": 0,
        }

    counts = _persist_orders(db, orders)
    return {
        "status": "success",
        **counts,
    }


def scrape_with_playwriter(db: DB) -> dict[str, Any]:
    """Execute Playwriter-powered scraping via OpenAI, then upsert results.

    This is a convenience function that uses the Playwriter backend with
    default settings. For more control, use scrape_amazon_orders() directly.

    Args:
        db: Database facade for persisting scraped data.

    Returns:
        Dictionary with status and summary of scraped data.
    """
    return scrape_amazon_orders(db, backend="playwriter")
