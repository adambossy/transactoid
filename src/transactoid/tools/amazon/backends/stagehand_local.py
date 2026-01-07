"""Stagehand LOCAL backend for Amazon order scraping."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import BaseModel, Field

from transactoid.tools.amazon.scraper import ScrapedItem, ScrapedOrder


class ExtractedItem(BaseModel):
    """Schema for extracting a single item from Amazon order."""

    asin: str = Field(..., description="Amazon Standard Identification Number")
    description: str = Field(..., description="Item name/description")
    price_cents: int = Field(..., description="Price in cents (e.g., $49.77 = 4977)")
    quantity: int = Field(default=1, description="Quantity ordered")


class ExtractedOrder(BaseModel):
    """Schema for extracting a single Amazon order."""

    order_id: str = Field(..., description="Order ID (e.g., 113-5524816-2451403)")
    order_date: str = Field(..., description="Order date in YYYY-MM-DD format")
    order_total_cents: int = Field(..., description="Total in cents")
    tax_cents: int = Field(default=0, description="Tax amount in cents")
    shipping_cents: int = Field(default=0, description="Shipping in cents")
    items: list[ExtractedItem] = Field(default_factory=list, description="Order items")


class ExtractedOrders(BaseModel):
    """Schema for extracting multiple orders from a page."""

    orders: list[ExtractedOrder] = Field(
        default_factory=list, description="List of orders on current page"
    )
    has_next_page: bool = Field(
        default=False, description="Whether there are more orders"
    )


class StagehandLocalBackend:
    """Amazon scraper backend using Stagehand LOCAL mode.

    This backend uses Stagehand with local Playwright to scrape Amazon
    order history. The browser will be visible for user authentication.
    """

    def __init__(
        self,
        model_name: str = "google/gemini-2.5-flash-preview-05-20",
        model_api_key: str | None = None,
    ) -> None:
        """Initialize the Stagehand LOCAL backend.

        Args:
            model_name: LLM model for Stagehand. Defaults to Gemini Flash.
            model_api_key: API key for the model. If None, reads from
                MODEL_API_KEY or GOOGLE_API_KEY environment variable.
        """
        self._model_name = model_name
        self._model_api_key = model_api_key or os.getenv(
            "MODEL_API_KEY", os.getenv("GOOGLE_API_KEY", "")
        )

    def scrape_order_history(
        self,
        year: int | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history via Stagehand LOCAL mode.

        Args:
            year: Optional year to filter orders.
            max_orders: Optional maximum orders to scrape.

        Returns:
            List of ScrapedOrder objects.
        """
        return asyncio.run(
            self._scrape_order_history_async(year=year, max_orders=max_orders)
        )

    async def _scrape_order_history_async(
        self,
        year: int | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Async implementation of order history scraping.

        Args:
            year: Optional year to filter orders.
            max_orders: Optional maximum orders to scrape.

        Returns:
            List of ScrapedOrder objects.
        """
        try:
            from stagehand import Stagehand, StagehandConfig  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "Stagehand is not installed. Install with: pip install stagehand"
            ) from e

        config = StagehandConfig(
            env="LOCAL",
            model_name=self._model_name,
            model_api_key=self._model_api_key,
            headless=False,  # Show browser for authentication
        )

        stagehand = Stagehand(config)
        await stagehand.init()

        try:
            # Build URL with optional year filter
            url = "https://www.amazon.com/your-orders/orders"
            if year:
                url = f"{url}?timeFilter=year-{year}"

            await stagehand.page.goto(url)

            # Wait for user to authenticate if needed
            await stagehand.page.act(
                "Wait for the page to fully load. If a login page appears, "
                "wait for the user to complete authentication."
            )

            all_orders: list[ScrapedOrder] = []
            page_num = 0

            while True:
                page_num += 1

                # Extract orders from current page
                extracted: Any = await stagehand.page.extract(
                    instruction=(
                        "Extract all orders visible on this page. "
                        "For each order, get the order ID, date (YYYY-MM-DD format), "
                        "total amount in cents, tax in cents, shipping in cents, "
                        "and all items with ASIN, description, price in cents, "
                        "and quantity. Also check if there's a 'Next' pagination link."
                    ),
                    schema=ExtractedOrders,
                )

                # Convert extracted orders to ScrapedOrder objects
                for order in extracted.orders:
                    scraped_order = ScrapedOrder(
                        order_id=order.order_id,
                        order_date=order.order_date,
                        order_total_cents=order.order_total_cents,
                        tax_cents=order.tax_cents,
                        shipping_cents=order.shipping_cents,
                        items=[
                            ScrapedItem(
                                asin=item.asin,
                                description=item.description,
                                price_cents=item.price_cents,
                                quantity=item.quantity,
                            )
                            for item in order.items
                        ],
                    )
                    all_orders.append(scraped_order)

                    # Check max_orders limit
                    if max_orders and len(all_orders) >= max_orders:
                        return all_orders[:max_orders]

                # Check for next page
                if not extracted.has_next_page:
                    break

                # Navigate to next page
                await stagehand.page.act("Click the 'Next' pagination button")

            return all_orders

        finally:
            await stagehand.close()
