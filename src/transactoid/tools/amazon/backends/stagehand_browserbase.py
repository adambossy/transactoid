"""Stagehand BROWSERBASE backend for Amazon order scraping."""

from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any

from pydantic import BaseModel, Field

from transactoid.tools.amazon.scraper import ScrapedItem, ScrapedOrder


class ExtractedItem(BaseModel):
    """Schema for extracting a single item from Amazon order."""

    model_config = {"populate_by_name": True}

    asin: str = Field(..., description="Amazon Standard Identification Number")
    description: str = Field(..., description="Item name/description")
    price_cents: int = Field(
        ..., alias="priceCents", description="Price in cents (e.g., $49.77 = 4977)"
    )
    quantity: int = Field(default=1, description="Quantity ordered")


class ExtractedOrder(BaseModel):
    """Schema for extracting a single Amazon order."""

    model_config = {"populate_by_name": True}

    order_id: str = Field(
        ..., alias="orderId", description="Order ID (e.g., 113-5524816-2451403)"
    )
    order_date: str = Field(
        ..., alias="orderDate", description="Order date in YYYY-MM-DD format"
    )
    order_total_cents: int = Field(
        ..., alias="orderTotalCents", description="Total in cents"
    )
    tax_cents: int = Field(
        default=0, alias="taxCents", description="Tax amount in cents"
    )
    shipping_cents: int = Field(
        default=0, alias="shippingCents", description="Shipping in cents"
    )
    items: list[ExtractedItem] = Field(default_factory=list, description="Order items")


class ExtractedOrders(BaseModel):
    """Schema for extracting multiple orders from a page."""

    model_config = {"populate_by_name": True}

    orders: list[ExtractedOrder] = Field(
        default_factory=list, description="List of orders on current page"
    )
    has_next_page: bool = Field(
        default=False, alias="hasNextPage", description="Whether there are more orders"
    )


class StagehandBrowserbaseBackend:
    """Amazon scraper backend using Stagehand with Browserbase.

    This backend uses Stagehand with Browserbase cloud browsers to scrape
    Amazon order history. Requires BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID
    environment variables.

    For authenticated scraping, use Browserbase contexts to persist login state:
    1. Create a context with `create_context()`
    2. Log in manually via Session Live View
    3. Reuse the context_id for future scraping sessions
    """

    def __init__(
        self,
        model_name: str = "google/gemini-2.5-flash",
        model_api_key: str | None = None,
        browserbase_api_key: str | None = None,
        browserbase_project_id: str | None = None,
        context_id: str | None = None,
        persist_context: bool = True,
        login_mode: bool = False,
    ) -> None:
        """Initialize the Stagehand Browserbase backend.

        Args:
            model_name: LLM model for Stagehand. Defaults to Gemini Flash.
            model_api_key: API key for the model. If None, reads from
                MODEL_API_KEY or GOOGLE_API_KEY environment variable.
            browserbase_api_key: Browserbase API key. If None, reads from
                BROWSERBASE_API_KEY environment variable.
            browserbase_project_id: Browserbase project ID. If None, reads from
                BROWSERBASE_PROJECT_ID environment variable.
            context_id: Optional Browserbase context ID for session persistence.
                Use `create_context()` to create a new context.
            persist_context: Whether to persist session changes to context.
                Defaults to True. Set to False for read-only access.
            login_mode: If True, wait for manual login via Session Live View
                instead of erroring when login is required. Use for first-time
                authentication setup.
        """
        self._model_name = model_name
        self._model_api_key = model_api_key or os.getenv(
            "MODEL_API_KEY", os.getenv("GOOGLE_API_KEY", "")
        )
        self._browserbase_api_key = browserbase_api_key or os.getenv(
            "BROWSERBASE_API_KEY", ""
        )
        self._browserbase_project_id = browserbase_project_id or os.getenv(
            "BROWSERBASE_PROJECT_ID", ""
        )
        self._context_id = context_id
        self._persist_context = persist_context
        self._login_mode = login_mode
        self._collected_orders: list[ScrapedOrder] = []  # Stores partial results

    @property
    def collected_orders(self) -> list[ScrapedOrder]:
        """Get orders collected so far (useful for partial recovery on failure)."""
        return self._collected_orders

    @classmethod
    def create_context(
        cls,
        browserbase_api_key: str | None = None,
        browserbase_project_id: str | None = None,
    ) -> str:
        """Create a new Browserbase context for session persistence.

        Contexts persist cookies, localStorage, and session tokens across
        browser sessions. Create a context once, then reuse its ID for
        future scraping sessions.

        Workflow:
        1. Call create_context() to get a context_id
        2. Create a backend with that context_id
        3. Start an interactive session to log in (use Session Live View)
        4. Future sessions with same context_id will be pre-authenticated

        Args:
            browserbase_api_key: Browserbase API key. If None, reads from
                BROWSERBASE_API_KEY environment variable.
            browserbase_project_id: Browserbase project ID. If None, reads from
                BROWSERBASE_PROJECT_ID environment variable.

        Returns:
            Context ID string to use in future sessions.

        Raises:
            ImportError: If browserbase package is not installed.
            ValueError: If API credentials are missing.
        """
        try:
            browserbase_module = importlib.import_module("browserbase")
        except ImportError as e:
            raise ImportError(
                "browserbase package not installed. "
                "Install with: pip install browserbase"
            ) from e
        browserbase_class = browserbase_module.Browserbase

        api_key = browserbase_api_key or os.getenv("BROWSERBASE_API_KEY", "")
        project_id = browserbase_project_id or os.getenv("BROWSERBASE_PROJECT_ID", "")

        if not api_key:
            raise ValueError("BROWSERBASE_API_KEY is required")
        if not project_id:
            raise ValueError("BROWSERBASE_PROJECT_ID is required")

        client = browserbase_class(api_key=api_key)
        context = client.contexts.create(project_id=project_id)
        return str(context.id)

    def get_session_live_view_url(self, session_id: str) -> str:
        """Get the Live View URL for interactive session access.

        Use this URL to manually log in to Amazon through the browser.

        Args:
            session_id: Browserbase session ID from a running session.

        Returns:
            URL to open in your browser for interactive access.
        """
        return f"https://www.browserbase.com/sessions/{session_id}"

    def scrape_order_history(
        self,
        year: int | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history via Stagehand Browserbase.

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

        if not self._browserbase_api_key:
            raise ValueError(
                "BROWSERBASE_API_KEY environment variable is required for "
                "Browserbase backend"
            )
        if not self._browserbase_project_id:
            raise ValueError(
                "BROWSERBASE_PROJECT_ID environment variable is required for "
                "Browserbase backend"
            )

        # Build session create params with optional context
        session_create_params: dict[str, Any] | None = None
        if self._context_id:
            session_create_params = {
                "browserSettings": {
                    "context": {
                        "id": self._context_id,
                        "persist": self._persist_context,
                    }
                }
            }

        config = stagehand_config_class(
            env="BROWSERBASE",
            apiKey=self._browserbase_api_key,
            projectId=self._browserbase_project_id,
            modelName=self._model_name,
            modelApiKey=self._model_api_key,
            browserbaseSessionCreateParams=session_create_params,
        )

        stagehand = stagehand_class(config)
        await stagehand.init()

        # Log session URL for debugging
        session_id = getattr(stagehand, "session_id", None)
        if session_id:
            session_url = self.get_session_live_view_url(session_id)
            print(f"[Browserbase] Session: {session_url}")
            if self._context_id:
                print(f"[Browserbase] Using context: {self._context_id}")

        try:
            # Build URL with optional year filter
            url = "https://www.amazon.com/your-orders/orders"
            if year:
                url = f"{url}?timeFilter=year-{year}"

            await stagehand.page.goto(url, timeout=60000)  # 60 second timeout

            # Check if login is required
            page = stagehand.page
            current_url = page.url

            if "signin" in current_url or "ap/signin" in current_url:
                if self._login_mode:
                    # Wait for user to log in via Session Live View
                    print("[Browserbase] Login required. Please log in via Live View.")
                    if session_id:
                        live_url = self.get_session_live_view_url(session_id)
                        print(f"[Browserbase] Open: {live_url}")
                    print("[Browserbase] Waiting up to 5 minutes for login...")

                    max_wait_seconds = 300  # 5 minutes
                    for i in range(max_wait_seconds):
                        current_url = page.url
                        if "your-orders" in current_url and "signin" not in current_url:
                            print("[Browserbase] Login successful! On orders page.")
                            break
                        if i > 0 and i % 30 == 0:
                            print(f"[Browserbase] Still waiting for login... ({i}s)")
                        await asyncio.sleep(1)
                    else:
                        raise TimeoutError(
                            "Timed out waiting for Amazon login. "
                            "Please log in within 5 minutes via Session Live View."
                        )
                elif self._context_id:
                    raise RuntimeError(
                        "Amazon login required despite using a context. "
                        "The context may have expired. Please:\n"
                        "1. Create a new context with create_context()\n"
                        "2. Log in via Session Live View using --login flag\n"
                        "3. Retry with the new context_id"
                    )
                else:
                    raise RuntimeError(
                        "Amazon login required. To use Browserbase:\n"
                        "1. Create a context: "
                        "ctx_id = StagehandBrowserbaseBackend.create_context()\n"
                        "2. Run with --login flag to authenticate\n"
                        "3. Reuse the same context_id for automated scraping"
                    )

            # Give the orders page time to fully load
            await asyncio.sleep(2)

            # Reset collected orders for this run
            self._collected_orders = []
            page_num = 0

            while True:
                page_num += 1
                print(f"[Browserbase] Extracting orders from page {page_num}...")

                # Extract orders from current page
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

                order_count = len(extracted.orders)
                print(f"[Browserbase] Found {order_count} orders on page {page_num}")

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
                    self._collected_orders.append(scraped_order)

                    # Check max_orders limit
                    if max_orders and len(self._collected_orders) >= max_orders:
                        return self._collected_orders[:max_orders]

                # Check for next page
                if not extracted.has_next_page:
                    break

                # Navigate to next page
                print("[Browserbase] Clicking 'Next' button...")
                await stagehand.page.act("Click the 'Next' pagination button")

            total = len(self._collected_orders)
            print(f"[Browserbase] Finished. Total orders: {total}")
            return self._collected_orders

        finally:
            await stagehand.close()
