"""Amazon order scraper with multiple browser backend support."""

from __future__ import annotations

import concurrent.futures
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB
    from transactoid.adapters.db.models import AmazonLoginProfileDB
    from transactoid.tools.amazon.backends.base import AmazonScraperBackend

load_dotenv(override=False)


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
    logger.info(
        "Selecting Amazon scraper backend: backend={} context_id_set={} login_mode={}",
        backend,
        context_id is not None,
        login_mode,
    )
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


def _persist_orders(db: DB, orders: list[ScrapedOrder]) -> tuple[int, int]:
    """Persist scraped orders to database.

    Args:
        db: Database facade for persisting data.
        orders: List of scraped orders to persist.

    Returns:
        Tuple of (orders_created, items_created) counts.
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

    return orders_created, items_created


def _ensure_auth(
    db: DB,
    profile: AmazonLoginProfileDB,
    backend: BackendType,
) -> AmazonLoginProfileDB:
    """Ensure a profile is authenticated, creating a context and logging in if needed.

    Uses an optimistic strategy: if a context_id already exists and the last auth
    was successful, treat the profile as ready without launching a new browser
    session. This avoids an extra browser spin-up just for checking.

    If no context_id exists, creates one via the backend, runs an interactive
    login flow, and persists the new context_id to the DB.

    Args:
        db: Database facade.
        profile: The login profile to authenticate.
        backend: Backend type to use.

    Returns:
        Updated profile (with context_id populated if newly created).

    Raises:
        Exception: If context creation or login fails.
    """
    if profile.browserbase_context_id is not None:
        # Optimistic: treat existing context as valid. If the session is
        # actually expired, the scrape phase will surface the error.
        logger.bind(profile_key=profile.profile_key).info(
            "Profile has existing context_id; treating as ready (optimistic)"
        )
        return profile

    # No context yet — create one and run interactive login.
    logger.bind(profile_key=profile.profile_key).info(
        "No context found; creating new Browserbase context and starting login flow"
    )

    if backend == "stagehand-browserbase":
        from transactoid.tools.amazon.backends.stagehand_browserbase import (
            StagehandBrowserbaseBackend,
        )

        context_id = StagehandBrowserbaseBackend.create_context()
        profile = db.set_amazon_login_context_id(
            profile_key=profile.profile_key, context_id=context_id
        )
        logger.bind(profile_key=profile.profile_key).info(
            "Created and persisted Browserbase context_id"
        )
    else:
        # Non-Browserbase backends do not use persistent contexts.
        logger.bind(profile_key=profile.profile_key).info(
            "Backend {} does not use persistent contexts; skipping context creation",
            backend,
        )
        context_id = None

    # Run login-mode scrape so the user can authenticate via Session Live View.
    backend_instance = _get_backend(backend, context_id=context_id, login_mode=True)
    backend_instance.scrape_order_history(year=None, max_orders=0)

    db.record_amazon_login_auth_result(
        profile_key=profile.profile_key, status="success"
    )
    logger.bind(profile_key=profile.profile_key).info(
        "Login flow completed; profile is now ready"
    )
    return profile


def _scrape_one_profile(
    db: DB,
    profile: AmazonLoginProfileDB,
    backend: BackendType,
    max_orders: int | None,
) -> dict[str, Any]:
    """Run a scrape for a single profile and persist results.

    Args:
        db: Database facade for persisting scraped data.
        profile: The authenticated login profile to scrape.
        backend: Backend type to use.
        max_orders: Optional cap on orders scraped.

    Returns:
        Per-profile result dict conforming to the result contract.
    """
    log = logger.bind(profile_key=profile.profile_key)
    log.info("Starting scrape for profile '{}'", profile.display_name)

    backend_instance = _get_backend(
        backend,
        context_id=profile.browserbase_context_id,
        login_mode=False,
    )
    orders = backend_instance.scrape_order_history(year=None, max_orders=max_orders)
    orders_created, items_created = _persist_orders(db, orders)

    log.success(
        "Scrape complete: orders_created={} items_created={}",
        orders_created,
        items_created,
    )
    return {
        "profile_key": profile.profile_key,
        "display_name": profile.display_name,
        "status": "success",
        "orders_created": orders_created,
        "items_created": items_created,
        "message": f"Scraped {orders_created} orders, {items_created} items",
    }


def _scrape_profile_with_retry(
    db: DB,
    profile: AmazonLoginProfileDB,
    backend: BackendType,
    max_orders: int | None,
) -> dict[str, Any]:
    """Scrape a single profile with one retry on failure.

    Args:
        db: Database facade.
        profile: The authenticated login profile to scrape.
        backend: Backend type to use.
        max_orders: Optional cap on orders scraped.

    Returns:
        Per-profile result dict conforming to the result contract.
    """
    log = logger.bind(profile_key=profile.profile_key)
    for attempt in range(2):
        try:
            return _scrape_one_profile(db, profile, backend, max_orders)
        except Exception as exc:
            if attempt == 0:
                log.warning("Scrape attempt 1 failed, retrying: {}", exc)
                continue
            log.error("Scrape failed after retry: {}", exc)
            return {
                "profile_key": profile.profile_key,
                "display_name": profile.display_name,
                "status": "error",
                "orders_created": 0,
                "items_created": 0,
                "message": str(exc),
            }

    # Unreachable; satisfies type checker.
    return {
        "profile_key": profile.profile_key,
        "display_name": profile.display_name,
        "status": "error",
        "orders_created": 0,
        "items_created": 0,
        "message": "Unknown error",
    }


def _run_parallel_scrape(
    db: DB,
    ready_profiles: list[AmazonLoginProfileDB],
    backend: BackendType,
    max_orders: int | None,
) -> list[dict[str, Any]]:
    """Run scraping for all ready profiles in parallel.

    Uses a ThreadPoolExecutor capped at min(4, len(ready_profiles)) workers.

    Args:
        db: Database facade.
        ready_profiles: Profiles that have passed the auth phase.
        backend: Backend type to use.
        max_orders: Optional cap on orders scraped per profile.

    Returns:
        List of per-profile result dicts.
    """
    concurrency = min(4, len(ready_profiles))
    profile_results: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                _scrape_profile_with_retry, db, profile, backend, max_orders
            ): profile
            for profile in ready_profiles
        }
        for future in concurrent.futures.as_completed(futures):
            profile_results.append(future.result())

    return profile_results


def _aggregate_results(
    profiles_total: int,
    profiles_ready: int,
    profile_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate per-profile results into a top-level summary.

    Args:
        profiles_total: Total number of enabled profiles.
        profiles_ready: Number of profiles that passed the auth phase.
        profile_results: List of per-profile result dicts.

    Returns:
        Top-level result dict conforming to the result contract.
    """
    succeeded = [r for r in profile_results if r["status"] == "success"]
    failed = [r for r in profile_results if r["status"] != "success"]
    total_orders = sum(r["orders_created"] for r in profile_results)
    total_items = sum(r["items_created"] for r in profile_results)

    if succeeded and len(succeeded) == len(profile_results):
        status = "success"
    elif succeeded:
        status = "partial"
    else:
        status = "error"

    return {
        "status": status,
        "orders_created": total_orders,
        "items_created": total_items,
        "profiles_total": profiles_total,
        "profiles_ready": profiles_ready,
        "profiles_succeeded": len(succeeded),
        "profiles_failed": len(failed),
        "message": (
            f"{len(succeeded)}/{profiles_ready} profiles succeeded, "
            f"{total_orders} orders, {total_items} items"
        ),
        "profile_results": profile_results,
    }


def _error_result(message: str, *, profiles_total: int = 0) -> dict[str, Any]:
    """Build a top-level error result with zero counts.

    Args:
        message: Human-readable error description.
        profiles_total: Total number of profiles considered (default 0).

    Returns:
        Top-level result dict with status "error".
    """
    return {
        "status": "error",
        "orders_created": 0,
        "items_created": 0,
        "profiles_total": profiles_total,
        "profiles_ready": 0,
        "profiles_succeeded": 0,
        "profiles_failed": 0,
        "message": message,
        "profile_results": [],
    }


def scrape_amazon_orders(
    db: DB,
    backend: BackendType = "stagehand-browserbase",
    max_orders: int | None = None,
) -> dict[str, Any]:
    """Scrape Amazon order history for all enabled login profiles.

    Runs a two-phase workflow:
    1. Sequential auth phase — validates (or establishes) authentication for
       each enabled profile, creating Browserbase contexts on first use.
    2. Parallel scrape phase — scrapes order history for all ready profiles
       concurrently (up to 4 workers), with one retry per profile on failure.

    Args:
        db: Database facade for persisting scraped data and profile state.
        backend: Browser backend to use ("playwriter", "stagehand", or
            "stagehand-browserbase").
        max_orders: Optional maximum number of orders to scrape per profile.

    Returns:
        Dictionary with top-level status and per-profile breakdown conforming
        to the result contract.
    """
    profiles = db.list_amazon_login_profiles(enabled_only=True)
    if not profiles:
        return _error_result(
            "No enabled Amazon login profiles configured. "
            "Use add_amazon_login to add a profile.",
            profiles_total=0,
        )

    logger.info(
        "Starting Amazon scrape: backend={} profiles={}",
        backend,
        len(profiles),
    )

    # Sequential auth phase
    ready_profiles: list[AmazonLoginProfileDB] = []
    for profile in profiles:
        log = logger.bind(profile_key=profile.profile_key)
        log.info("Auth phase: checking profile '{}'", profile.display_name)
        try:
            authenticated = _ensure_auth(db, profile, backend)
            ready_profiles.append(authenticated)
            log.info("Profile '{}' ready for scraping", profile.display_name)
        except Exception as exc:
            log.error("Auth failed for profile '{}': {}", profile.display_name, exc)
            db.record_amazon_login_auth_result(
                profile_key=profile.profile_key,
                status="failed",
                error=str(exc),
            )

    if not ready_profiles:
        return _error_result(
            "All profiles failed authentication.",
            profiles_total=len(profiles),
        )

    logger.info(
        "{}/{} profiles passed auth; starting parallel scrape",
        len(ready_profiles),
        len(profiles),
    )

    # Parallel scrape phase
    profile_results = _run_parallel_scrape(db, ready_profiles, backend, max_orders)

    return _aggregate_results(len(profiles), len(ready_profiles), profile_results)


def scrape_with_playwriter(db: DB) -> dict[str, Any]:
    """Execute Playwriter-powered scraping via OpenAI, then upsert results.

    This is a convenience wrapper around scrape_amazon_orders() using the
    Playwriter backend. For profile-based multi-login scraping, use
    scrape_amazon_orders() directly.

    Args:
        db: Database facade for persisting scraped data.

    Returns:
        Dictionary with status and summary of scraped data.
    """
    return scrape_amazon_orders(db, backend="playwriter")
