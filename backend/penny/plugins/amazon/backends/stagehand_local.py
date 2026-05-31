"""Stagehand LOCAL backend for Amazon order scraping."""

from __future__ import annotations

import asyncio
from datetime import date
import importlib
import os
from typing import Any

from pydantic import BaseModel, Field

from penny.plugins.amazon.backends.stagehand_browserbase import (
    PageOutcome,
    _page_url,
    _years_for_window,
)
from penny.plugins.amazon.scraper import ScrapedItem, ScrapedOrder


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
        self._collected_orders: list[ScrapedOrder] = []

    def scrape_order_history(
        self,
        *,
        since: date | None = None,
        until: date | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history via Stagehand LOCAL mode.

        Args:
            since: Inclusive lower bound on ``order_date``.
            until: Inclusive upper bound on ``order_date``.
            max_orders: Optional maximum orders across all visited years.

        Returns:
            List of ScrapedOrder objects.
        """
        try:
            loop = asyncio.get_running_loop()
            nest_asyncio_module = importlib.import_module("nest_asyncio")
            apply = getattr(nest_asyncio_module, "apply", None)
            if callable(apply):
                apply()
            return loop.run_until_complete(
                self._scrape_order_history_async(
                    since=since, until=until, max_orders=max_orders
                )
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(
                    self._scrape_order_history_async(
                        since=since, until=until, max_orders=max_orders
                    )
                )
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    async def _scrape_order_history_async(
        self,
        *,
        since: date | None,
        until: date | None,
        max_orders: int | None,
    ) -> list[ScrapedOrder]:
        """Async implementation of order history scraping."""
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
            base_url = "https://www.amazon.com/your-orders/orders"
            await stagehand.page.goto(base_url, timeout=60000)

            # Wait for user to authenticate if needed
            page = stagehand.page
            max_wait_seconds = 300  # 5 minutes to log in

            for _ in range(max_wait_seconds):
                current_url = page.url
                if "your-orders" in current_url and "signin" not in current_url:
                    print(f"[Stagehand] Detected orders page: {current_url}")
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError(
                    "Timed out waiting for Amazon login. "
                    "Please log in within 5 minutes."
                )

            year_filters = _years_for_window(
                since=since,
                until=until,
                max_orders=max_orders,
                today=date.today(),
            )
            print(
                f"[Stagehand] Year filters resolved: {year_filters} "
                f"(since={since} until={until})"
            )

            self._collected_orders = []

            for year_filter in year_filters:
                if year_filter is not None:
                    year_url = _page_url(base_url, year_filter, page_num=1)
                    await stagehand.page.goto(year_url, timeout=60000)

                print("[Stagehand] Waiting 2 seconds for page to fully load...")
                await asyncio.sleep(2)
                print("[Stagehand] Starting extraction loop...")

                outcome = await self._extract_pages_in_current_view(
                    stagehand,
                    base_url=base_url,
                    since=since,
                    until=until,
                    max_orders=max_orders,
                    year_filter=year_filter,
                )
                if outcome == "limit_hit":
                    return self._collected_orders[:max_orders]
                if outcome == "past_floor":
                    print(
                        f"[Stagehand] Year {year_filter} fully older than "
                        f"since={since}; halting iteration"
                    )
                    break

            print(
                f"[Stagehand] Finished scraping. Total orders: "
                f"{len(self._collected_orders)}"
            )
            return self._collected_orders

        finally:
            print("[Stagehand] Closing browser...")
            await stagehand.close()

    async def _extract_pages_in_current_view(
        self,
        stagehand: Any,
        *,
        base_url: str,
        since: date | None,
        until: date | None,
        max_orders: int | None,
        year_filter: int | None,
    ) -> PageOutcome:
        """Extract every paginated page in the current view.

        Returns ``"limit_hit"`` when ``max_orders`` is reached, ``"past_floor"``
        when the current year produced ≥1 order all strictly older than
        ``since``, or ``"continue"`` to advance to the next year.
        """
        view_label = f"year={year_filter}" if year_filter is not None else "default"
        page_num = 0
        had_extractions = False
        all_older_than_since = True
        while True:
            page_num += 1
            print(
                f"[Stagehand] Extracting orders from page {page_num} ({view_label})..."
            )
            print(f"[Stagehand] Current URL: {stagehand.page.url}")

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
                print(
                    f"[Stagehand] Found {order_count} orders on page {page_num} "
                    f"({view_label})"
                )
            except Exception as extract_error:
                print(f"[Stagehand] ERROR during extraction: {extract_error}")
                import traceback

                traceback.print_exc()
                raise

            for order in extracted.orders:
                had_extractions = True
                try:
                    parsed_date = date.fromisoformat(order.order_date)
                except ValueError:
                    print(
                        f"[Stagehand] Skipping order {order.order_id} with "
                        f"unparsable date '{order.order_date}'"
                    )
                    continue

                if until is not None and parsed_date > until:
                    continue
                if since is not None and parsed_date < since:
                    continue
                if since is None or parsed_date >= since:
                    all_older_than_since = False

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
                self._collected_orders.append(scraped_order)

                if max_orders and len(self._collected_orders) >= max_orders:
                    return "limit_hit"

            if order_count == 0:
                if since is not None and had_extractions and all_older_than_since:
                    return "past_floor"
                return "continue"

            if not extracted.has_next_page:
                if since is not None and had_extractions and all_older_than_since:
                    return "past_floor"
                return "continue"

            next_url = _page_url(base_url, year_filter, page_num=page_num + 1)
            print(f"[Stagehand] Navigating to next page: {next_url}")
            await stagehand.page.goto(next_url, timeout=60000)
            await asyncio.sleep(2)
