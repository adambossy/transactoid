"""Stagehand BROWSERBASE backend for Amazon order scraping."""

from __future__ import annotations

import asyncio
from datetime import date
import importlib
import os
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from penny.plugins.amazon.scraper import ScrapedItem, ScrapedOrder

# Maximum backward-iteration window when no `since` is provided. Amazon's
# year-filter dropdown lists years back to ~2010; this keeps iteration bounded
# even when the orchestrator's DB-derived floor is absent.
_DEFAULT_FLOOR_YEARS = 20

# Browserbase per-session lifetime cap (seconds). Default is ~5 min on free
# plans, which is too short for multi-page year scrapes (~30s/page). Bumped so
# a single year of orders can complete in one session without retry-thrashing.
_DEFAULT_SESSION_TIMEOUT_SECONDS = 1800

PageOutcome = Literal["continue", "limit_hit", "past_floor"]


_ORDERS_PER_PAGE = 10


def _page_url(base_url: str, year_filter: int | None, page_num: int) -> str:
    """URL for ``page_num`` (1-indexed) of the orders view.

    Why: Amazon's "Next" link is an SPA-style hyperlink that triggers a
    soft-navigation; under Stagehand the CDP target on the old frame is
    destroyed before Stagehand re-attaches, raising ``Page.evaluate: Target
    page, context or browser has been closed``. Direct ``goto()`` to the
    fully-qualified URL sidesteps that race.
    """
    params: list[str] = []
    if year_filter is not None:
        params.append(f"timeFilter=year-{year_filter}")
    if page_num > 1:
        params.append(f"startIndex={(page_num - 1) * _ORDERS_PER_PAGE}")
    if not params:
        return base_url
    return f"{base_url}?{'&'.join(params)}"


def _years_for_window(
    *,
    since: date | None,
    until: date | None,
    max_orders: int | None,
    today: date,
    floor_years: int = _DEFAULT_FLOOR_YEARS,
) -> list[int | None]:
    """Compute the year-filter URLs to visit for a given date window.

    Returns a most-recent-first list of years to iterate via Amazon's
    ``?timeFilter=year-{Y}`` URL parameter. A single ``None`` entry means
    "use Amazon's default view" (typically past 3 months) and is returned
    only when no constraint is provided at all.
    """
    if since is None and until is None and max_orders is None:
        return [None]

    upper = until.year if until is not None else today.year
    if upper > today.year:
        upper = today.year

    if since is not None:
        lower = since.year
    else:
        lower = today.year - floor_years

    if lower > upper:
        return []

    return list(range(upper, lower - 1, -1))


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
        *,
        since: date | None = None,
        until: date | None = None,
        max_orders: int | None = None,
    ) -> list[ScrapedOrder]:
        """Scrape Amazon order history via Stagehand Browserbase.

        Args:
            since: Inclusive lower bound on ``order_date`` (already DB-floored
                by orchestrator).
            until: Inclusive upper bound on ``order_date``.
            max_orders: Optional maximum orders across all visited years.

        Returns:
            List of ScrapedOrder objects.
        """
        logger.info(
            "Browserbase scrape_order_history start: since={} until={} "
            "max_orders={} context_id_set={} login_mode={}",
            since,
            until,
            max_orders,
            self._context_id is not None,
            self._login_mode,
        )
        try:
            loop = asyncio.get_running_loop()
            logger.debug("Browserbase backend detected active event loop")
            nest_asyncio_module = importlib.import_module("nest_asyncio")
            apply = getattr(nest_asyncio_module, "apply", None)
            if callable(apply):
                apply()
                logger.debug("Applied nest_asyncio for nested event loop support")
            return loop.run_until_complete(
                self._scrape_order_history_async(
                    since=since, until=until, max_orders=max_orders
                )
            )
        except RuntimeError:
            logger.debug("Browserbase backend using manual event loop")
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
        logger.info("Browserbase async scrape starting")
        try:
            stagehand_module = importlib.import_module("stagehand")
        except ImportError as e:
            raise ImportError(
                "Stagehand is not installed. Install with: pip install stagehand"
            ) from e
        logger.debug("Imported stagehand module successfully")
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
        logger.info("Browserbase credentials detected in environment/config")

        # Build session create params: bump per-session timeout (default ~5 min
        # on free plans is too short) and attach the persistent context if any.
        session_create_params: dict[str, Any] = {
            "timeout": _DEFAULT_SESSION_TIMEOUT_SECONDS,
        }
        if self._context_id:
            session_create_params["browserSettings"] = {
                "context": {
                    "id": self._context_id,
                    "persist": self._persist_context,
                }
            }
            logger.info(
                "Using Browserbase context_id={} (persist={}, timeout={}s)",
                self._context_id,
                self._persist_context,
                _DEFAULT_SESSION_TIMEOUT_SECONDS,
            )
        else:
            logger.info(
                "No Browserbase context ID configured (timeout={}s)",
                _DEFAULT_SESSION_TIMEOUT_SECONDS,
            )

        config = stagehand_config_class(
            env="BROWSERBASE",
            apiKey=self._browserbase_api_key,
            projectId=self._browserbase_project_id,
            modelName=self._model_name,
            modelApiKey=self._model_api_key,
            browserbaseSessionCreateParams=session_create_params,
        )

        logger.info("Initializing Stagehand Browserbase session")
        stagehand = stagehand_class(config)
        await stagehand.init()
        logger.info("Stagehand init complete")

        # Log session URL for debugging
        session_id = getattr(stagehand, "session_id", None)
        if session_id:
            session_url = self.get_session_live_view_url(session_id)
            logger.info("Browserbase session live view: {}", session_url)
            if self._context_id:
                logger.info(
                    "Browserbase session attached to context: {}", self._context_id
                )
        else:
            logger.warning("Stagehand session_id was not available after init")

        try:
            # Initial navigation: base orders URL is enough to trigger any
            # required login flow. Per-year navigation happens after login.
            base_url = "https://www.amazon.com/your-orders/orders"
            logger.info("Navigating to Amazon orders URL: {}", base_url)
            await stagehand.page.goto(base_url, timeout=60000)
            logger.info("Navigation to Amazon orders URL completed")

            # Check if login is required
            page = stagehand.page
            current_url = page.url
            logger.info("Current page URL after navigation: {}", current_url)

            if "signin" in current_url or "ap/signin" in current_url:
                logger.warning("Amazon sign-in page detected")
                if self._login_mode:
                    # Wait for user to log in via Session Live View
                    logger.info(
                        "Login mode enabled; waiting for manual login in Live View"
                    )
                    if session_id:
                        live_url = self.get_session_live_view_url(session_id)
                        logger.info(
                            "Open Browserbase Live View for login: {}", live_url
                        )
                    logger.info("Waiting up to 5 minutes for Amazon login")

                    max_wait_seconds = 300  # 5 minutes
                    for i in range(max_wait_seconds):
                        current_url = page.url
                        if "your-orders" in current_url and "signin" not in current_url:
                            logger.info("Login successful; now on orders page")
                            break
                        if i > 0 and i % 30 == 0:
                            logger.info("Still waiting for login ({}s elapsed)", i)
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

            year_filters = _years_for_window(
                since=since,
                until=until,
                max_orders=max_orders,
                today=date.today(),
            )
            logger.info(
                "Browserbase year_filters resolved: {} (since={} until={})",
                year_filters,
                since,
                until,
            )

            # Reset collected orders for this run
            self._collected_orders = []

            for year_filter in year_filters:
                if year_filter is not None:
                    year_url = _page_url(base_url, year_filter, page_num=1)
                    logger.info("Navigating to year-filtered URL: {}", year_url)
                    await stagehand.page.goto(year_url, timeout=60000)

                # Give the orders page time to fully load
                await asyncio.sleep(2)

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
                    logger.info(
                        "Year {} fully older than since={}; halting iteration",
                        year_filter,
                        since,
                    )
                    break

            total = len(self._collected_orders)
            logger.info(
                "Browserbase scrape finished. Total orders collected: {}", total
            )
            return self._collected_orders

        finally:
            logger.info("Closing Stagehand Browserbase session")
            await stagehand.close()
            logger.info("Stagehand Browserbase session closed")

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
        """Extract all paginated order rows visible in the current view.

        Appends orders that fall within ``since``/``until`` to
        ``self._collected_orders``. Returns one of:

        - ``"limit_hit"``: ``max_orders`` cap reached; caller stops iterating.
        - ``"past_floor"``: this year produced ≥1 extracted order and every
          one was strictly older than ``since``; caller stops iterating.
        - ``"continue"``: caller should advance to the next year (if any).
        """
        page_num = 0
        view_label = f"year={year_filter}" if year_filter is not None else "default"
        had_extractions = False
        all_older_than_since = True
        while True:
            page_num += 1
            logger.info("Extracting orders from page {} ({})", page_num, view_label)
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
            logger.debug(
                "Stagehand extraction returned payload for page {} ({})",
                page_num,
                view_label,
            )
            order_count = len(extracted.orders)
            logger.info(
                "Found {} orders on page {} ({})", order_count, page_num, view_label
            )

            for order in extracted.orders:
                had_extractions = True
                try:
                    parsed_date = date.fromisoformat(order.order_date)
                except ValueError:
                    logger.warning(
                        "Skipping order {} with unparsable date '{}'",
                        order.order_id,
                        order.order_date,
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
                    logger.info(
                        "Reached max_orders limit ({}), stopping extraction",
                        max_orders,
                    )
                    return "limit_hit"

            if order_count == 0:
                logger.info(
                    "Page {} ({}) returned 0 orders; ending pagination",
                    page_num,
                    view_label,
                )
                if since is not None and had_extractions and all_older_than_since:
                    return "past_floor"
                return "continue"

            if not extracted.has_next_page:
                logger.info(
                    "No next page detected after page {} ({})", page_num, view_label
                )
                if since is not None and had_extractions and all_older_than_since:
                    return "past_floor"
                return "continue"

            next_url = _page_url(base_url, year_filter, page_num=page_num + 1)
            logger.info("Navigating to next page URL: {}", next_url)
            await stagehand.page.goto(next_url, timeout=60000)
            await asyncio.sleep(2)
            logger.info("Pagination navigation completed")
