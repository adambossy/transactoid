"""Stagehand LOCAL backend for Amazon order scraping."""

from __future__ import annotations

import asyncio
import importlib
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
        model_name: str = "google/gemini-2.5-flash",
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
        try:
            # Check if we're already in an async context
            loop = asyncio.get_running_loop()
            # Already in async context - use nest_asyncio to allow nested loops
            nest_asyncio_module = importlib.import_module("nest_asyncio")
            apply = getattr(nest_asyncio_module, "apply", None)
            if callable(apply):
                apply()
            return loop.run_until_complete(
                self._scrape_order_history_async(year=year, max_orders=max_orders)
            )
        except RuntimeError:
            # No running loop, safe to use asyncio.run()
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
            stagehand_module = importlib.import_module("stagehand")
        except ImportError as e:
            raise ImportError(
                "Stagehand is not installed. Install with: pip install stagehand"
            ) from e
        stagehand_class = stagehand_module.Stagehand
        stagehand_config_class = stagehand_module.StagehandConfig

        print(f"[Stagehand] Initializing with model: {self._model_name}")
        print(f"[Stagehand] API key configured: {bool(self._model_api_key)}")

        config = stagehand_config_class(
            env="LOCAL",
            model_name=self._model_name,
            model_api_key=self._model_api_key,
            headless=False,  # Show browser for authentication
        )

        stagehand = stagehand_class(config)
        print("[Stagehand] Config created, initializing browser...")
        await stagehand.init()
        print("[Stagehand] Browser initialized successfully")

        try:
            # Build URL with optional year filter
            url = "https://www.amazon.com/your-orders/orders"
            if year:
                url = f"{url}?timeFilter=year-{year}"

            await stagehand.page.goto(url, timeout=60000)  # 60 second timeout

            # Wait for user to authenticate if needed
            # Check if we're on a login page and wait for user to complete login
            page = stagehand.page
            max_wait_seconds = 300  # 5 minutes to log in

            for _ in range(max_wait_seconds):
                current_url = page.url
                # Check if we're on the orders page (not login/signin)
                if "your-orders" in current_url and "signin" not in current_url:
                    print(f"[Stagehand] Detected orders page: {current_url}")
                    break
                # Still on login page, wait for user
                await asyncio.sleep(1)
            else:
                raise TimeoutError(
                    "Timed out waiting for Amazon login. "
                    "Please log in within 5 minutes."
                )

            # Give the orders page time to fully load
            print("[Stagehand] Waiting 2 seconds for page to fully load...")
            await asyncio.sleep(2)
            print("[Stagehand] Starting extraction loop...")

            all_orders: list[ScrapedOrder] = []
            page_num = 0

            while True:
                page_num += 1

                # Extract orders from current page
                print(f"[Stagehand] Extracting orders from page {page_num}...")
                print(f"[Stagehand] Current URL: {page.url}")

                try:
                    extracted: Any = await stagehand.page.extract(
                        instruction=(
                            "Extract all orders visible on this page. "
                            "For each order, get the order ID, "
                            "date (YYYY-MM-DD format), "
                            "total amount in cents, tax in cents, shipping in cents, "
                            "and all items with ASIN, description, price in cents, "
                            "and quantity. Also check if there's a 'Next' link."
                        ),
                        schema=ExtractedOrders,
                    )
                    print(f"[Stagehand] Extraction result: {extracted}")
                    order_count = len(extracted.orders)
                    print(f"[Stagehand] Found {order_count} orders on page {page_num}")
                except Exception as extract_error:
                    print(f"[Stagehand] ERROR during extraction: {extract_error}")
                    import traceback

                    traceback.print_exc()
                    raise

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
                print("[Stagehand] Clicking 'Next' button...")
                await stagehand.page.act("Click the 'Next' pagination button")

            print(f"[Stagehand] Finished scraping. Total orders: {len(all_orders)}")
            return all_orders

        finally:
            print("[Stagehand] Closing browser...")
            await stagehand.close()
