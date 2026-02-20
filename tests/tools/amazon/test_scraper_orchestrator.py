"""Tests for the scrape_amazon_orders orchestrator flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from transactoid.adapters.db.facade import DB
from transactoid.tools.amazon.scraper import (
    ScrapedItem,
    ScrapedOrder,
    _aggregate_results,
    _scrape_profile_with_retry,
    scrape_amazon_orders,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_test_db(tmp_path: Path) -> DB:
    """Create a test database with schema."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


def _make_profile(
    profile_key: str = "primary",
    display_name: str = "Primary",
    context_id: str | None = None,
) -> MagicMock:
    """Build a mock AmazonLoginProfileDB with sensible defaults."""
    profile = MagicMock()
    profile.profile_key = profile_key
    profile.display_name = display_name
    profile.browserbase_context_id = context_id
    return profile


def _make_scraped_orders(count: int = 2) -> list[ScrapedOrder]:
    """Build a list of minimal ScrapedOrder objects."""
    return [
        ScrapedOrder(
            order_id=f"order-{idx}",
            order_date="2024-01-15",
            order_total_cents=1000,
            tax_cents=80,
            shipping_cents=0,
            items=[
                ScrapedItem(
                    asin=f"ASIN{idx}",
                    description=f"Item {idx}",
                    price_cents=920,
                    quantity=1,
                )
            ],
        )
        for idx in range(count)
    ]


# ---------------------------------------------------------------------------
# scrape_amazon_orders — no enabled profiles
# ---------------------------------------------------------------------------


class TestScrapeAmazonOrdersNoProfiles:
    def test_scrape_amazon_orders_no_profiles_returns_error(self) -> None:
        # input
        db = MagicMock()
        db.list_amazon_login_profiles.return_value = []

        # act
        result = scrape_amazon_orders(db)

        # assert
        assert result["status"] == "error"
        assert "no enabled" in result["message"].lower()
        assert result["profiles_total"] == 0
        assert result["orders_created"] == 0
        assert result["items_created"] == 0


# ---------------------------------------------------------------------------
# scrape_amazon_orders — profile with existing context
# ---------------------------------------------------------------------------


class TestScrapeAmazonOrdersWithExistingContext:
    def test_scrape_amazon_orders_profile_with_context_scrapes_directly(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        mock_orders = _make_scraped_orders(2)

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = mock_orders
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # assert
        assert result["status"] == "success"
        assert result["orders_created"] == 2
        assert result["items_created"] == 2
        assert result["profiles_succeeded"] == 1
        assert result["profiles_failed"] == 0

    def test_scrape_amazon_orders_profile_with_context_calls_backend_without_login_mode(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db)

        # assert: backend called with login_mode=False and correct context_id
        mock_get_backend.assert_called_once_with(
            "stagehand-browserbase",
            context_id="ctx-existing",
            login_mode=False,
        )


# ---------------------------------------------------------------------------
# scrape_amazon_orders — profile without context triggers login flow
#
# _ensure_auth imports StagehandBrowserbaseBackend lazily inside its body so
# we patch _ensure_auth directly instead of patching the class attribute.
# ---------------------------------------------------------------------------


class TestScrapeAmazonOrdersWithoutContext:
    def test_scrape_amazon_orders_profile_without_context_triggers_login(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id=None)
        updated_profile = _make_profile(context_id="new-ctx-123")
        db.list_amazon_login_profiles.return_value = [profile]

        # Simulate _ensure_auth persisting context and returning updated profile
        def fake_ensure_auth(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
        ) -> MagicMock:
            db_arg.set_amazon_login_context_id(
                profile_key=profile_arg.profile_key, context_id="new-ctx-123"
            )
            return updated_profile

        with (
            patch(
                "transactoid.tools.amazon.scraper._ensure_auth",
                side_effect=fake_ensure_auth,
            ),
            patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend,
        ):
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # assert: context persisted to DB
        db.set_amazon_login_context_id.assert_called_once_with(
            profile_key="primary", context_id="new-ctx-123"
        )
        assert result["status"] == "success"

    def test_scrape_amazon_orders_no_context_login_backend_uses_login_mode(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id=None)
        updated_profile = _make_profile(context_id="new-ctx-456")
        db.list_amazon_login_profiles.return_value = [profile]

        # Fake _ensure_auth: no context yet, simulates creating and returning updated
        def fake_ensure_auth(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
        ) -> MagicMock:
            # Mimic what the real _ensure_auth does when no context exists:
            # calls _get_backend with login_mode=True then returns updated profile
            backend_instance = _get_backend_mock(
                backend_arg,
                context_id="new-ctx-456",
                login_mode=True,
            )
            backend_instance.scrape_order_history(year=None, max_orders=0)
            return updated_profile

        _get_backend_mock = MagicMock(return_value=MagicMock())
        scrape_backend = MagicMock()
        scrape_backend.scrape_order_history.return_value = []

        with (
            patch(
                "transactoid.tools.amazon.scraper._ensure_auth",
                side_effect=fake_ensure_auth,
            ),
            patch(
                "transactoid.tools.amazon.scraper._get_backend",
                return_value=scrape_backend,
            ) as mock_get_backend,
        ):
            # act
            scrape_amazon_orders(db)

        # assert: scrape backend invoked with login_mode=False for the scrape phase
        mock_get_backend.assert_called_once_with(
            "stagehand-browserbase",
            context_id="new-ctx-456",
            login_mode=False,
        )

    def test_scrape_amazon_orders_auth_failure_records_failed_status(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id=None)
        db.list_amazon_login_profiles.return_value = [profile]

        with patch(
            "transactoid.tools.amazon.scraper._ensure_auth",
            side_effect=RuntimeError("Network timeout"),
        ):
            # act
            result = scrape_amazon_orders(db)

        # assert: auth failure recorded and error returned
        db.record_amazon_login_auth_result.assert_called_once_with(
            profile_key="primary",
            status="failed",
            error="Network timeout",
        )
        assert result["status"] == "error"
        assert "failed authentication" in result["message"].lower()


# ---------------------------------------------------------------------------
# _aggregate_results — status derivation
# ---------------------------------------------------------------------------


class TestAggregateResults:
    def test_aggregate_results_all_success(self) -> None:
        # input
        profile_results: list[dict[str, Any]] = [
            {
                "profile_key": "a",
                "display_name": "A",
                "status": "success",
                "orders_created": 3,
                "items_created": 5,
                "message": "",
            },
            {
                "profile_key": "b",
                "display_name": "B",
                "status": "success",
                "orders_created": 2,
                "items_created": 4,
                "message": "",
            },
        ]

        # act
        result = _aggregate_results(2, 2, profile_results)

        # assert
        assert result["status"] == "success"
        assert result["orders_created"] == 5
        assert result["items_created"] == 9
        assert result["profiles_succeeded"] == 2
        assert result["profiles_failed"] == 0

    def test_aggregate_results_mixed_returns_partial(self) -> None:
        # input
        profile_results: list[dict[str, Any]] = [
            {
                "profile_key": "a",
                "display_name": "A",
                "status": "success",
                "orders_created": 3,
                "items_created": 5,
                "message": "",
            },
            {
                "profile_key": "b",
                "display_name": "B",
                "status": "error",
                "orders_created": 0,
                "items_created": 0,
                "message": "Failed",
            },
        ]

        # act
        result = _aggregate_results(2, 2, profile_results)

        # assert
        assert result["status"] == "partial"
        assert result["profiles_succeeded"] == 1
        assert result["profiles_failed"] == 1
        assert result["orders_created"] == 3
        assert result["items_created"] == 5

    def test_aggregate_results_all_failed_returns_error(self) -> None:
        # input
        profile_results: list[dict[str, Any]] = [
            {
                "profile_key": "a",
                "display_name": "A",
                "status": "error",
                "orders_created": 0,
                "items_created": 0,
                "message": "Timeout",
            }
        ]

        # act
        result = _aggregate_results(1, 1, profile_results)

        # assert
        assert result["status"] == "error"
        assert result["profiles_succeeded"] == 0
        assert result["profiles_failed"] == 1

    def test_aggregate_results_preserves_profile_results(self) -> None:
        # input
        profile_results: list[dict[str, Any]] = [
            {
                "profile_key": "a",
                "display_name": "A",
                "status": "success",
                "orders_created": 1,
                "items_created": 2,
                "message": "ok",
            }
        ]

        # act
        result = _aggregate_results(1, 1, profile_results)

        # assert
        assert result["profile_results"] == profile_results

    def test_aggregate_results_passes_counts_through(self) -> None:
        # input
        profile_results: list[dict[str, Any]] = []

        # act
        result = _aggregate_results(5, 3, profile_results)

        # assert
        assert result["profiles_total"] == 5
        assert result["profiles_ready"] == 3


# ---------------------------------------------------------------------------
# _scrape_profile_with_retry
# ---------------------------------------------------------------------------


class TestScrapeProfileWithRetry:
    def test_scrape_profile_with_retry_retries_once_on_failure(self) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-abc")
        call_count = 0

        def fake_scrape_one(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
            max_orders_arg: Any,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Transient failure")
            return {
                "profile_key": "primary",
                "display_name": "Primary",
                "status": "success",
                "orders_created": 1,
                "items_created": 2,
                "message": "ok",
            }

        with patch(
            "transactoid.tools.amazon.scraper._scrape_one_profile",
            side_effect=fake_scrape_one,
        ):
            # act
            result = _scrape_profile_with_retry(
                db, profile, "stagehand-browserbase", None
            )

        # assert
        assert call_count == 2
        assert result["status"] == "success"

    def test_scrape_profile_with_retry_returns_error_after_two_failures(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-abc")

        with patch(
            "transactoid.tools.amazon.scraper._scrape_one_profile",
            side_effect=RuntimeError("Persistent failure"),
        ):
            # act
            result = _scrape_profile_with_retry(
                db, profile, "stagehand-browserbase", None
            )

        # assert
        assert result["status"] == "error"
        assert "Persistent failure" in result["message"]
        assert result["orders_created"] == 0
        assert result["items_created"] == 0

    def test_scrape_profile_with_retry_no_retry_on_success(self) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-abc")
        call_count = 0

        def fake_scrape_one(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
            max_orders_arg: Any,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "profile_key": "primary",
                "display_name": "Primary",
                "status": "success",
                "orders_created": 3,
                "items_created": 6,
                "message": "ok",
            }

        with patch(
            "transactoid.tools.amazon.scraper._scrape_one_profile",
            side_effect=fake_scrape_one,
        ):
            # act
            _scrape_profile_with_retry(db, profile, "stagehand-browserbase", None)

        # assert: called exactly once — no retry when it succeeds
        assert call_count == 1


# ---------------------------------------------------------------------------
# Result shape completeness
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_scrape_amazon_orders_result_shape_contains_required_keys(self) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # expected
        required_keys = {
            "status",
            "orders_created",
            "items_created",
            "profiles_total",
            "profiles_ready",
            "profiles_succeeded",
            "profiles_failed",
            "message",
            "profile_results",
        }

        # assert
        assert required_keys.issubset(result.keys())

    def test_scrape_amazon_orders_error_result_shape_contains_required_keys(
        self,
    ) -> None:
        # input
        db = MagicMock()
        db.list_amazon_login_profiles.return_value = []

        # act
        result = scrape_amazon_orders(db)

        # expected
        required_keys = {
            "status",
            "orders_created",
            "items_created",
            "profiles_total",
            "profiles_ready",
            "profiles_succeeded",
            "profiles_failed",
            "message",
            "profile_results",
        }

        # assert
        assert required_keys.issubset(result.keys())

    def test_scrape_amazon_orders_profile_results_per_profile_shape(self) -> None:
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # assert: per-profile result has required keys
        per_profile_required_keys = {
            "profile_key",
            "display_name",
            "status",
            "orders_created",
            "items_created",
            "message",
        }
        assert len(result["profile_results"]) == 1
        assert per_profile_required_keys.issubset(result["profile_results"][0].keys())


# ---------------------------------------------------------------------------
# Multiple profiles — parallel scrape
# ---------------------------------------------------------------------------


class TestMultipleProfiles:
    def test_scrape_amazon_orders_multiple_profiles_all_success(self) -> None:
        # input
        db = MagicMock()
        profile_a = _make_profile("profile_a", "Account A", context_id="ctx-a")
        profile_b = _make_profile("profile_b", "Account B", context_id="ctx-b")
        db.list_amazon_login_profiles.return_value = [profile_a, profile_b]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = _make_scraped_orders(1)
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # assert
        assert result["status"] == "success"
        assert result["profiles_total"] == 2
        assert result["profiles_succeeded"] == 2
        assert result["profiles_failed"] == 0
        assert result["orders_created"] == 2  # 1 order per profile
        assert result["items_created"] == 2  # 1 item per profile

    def test_scrape_amazon_orders_one_profile_fails_returns_partial(self) -> None:
        # input
        db = MagicMock()
        profile_a = _make_profile("profile_a", "Account A", context_id="ctx-a")
        profile_b = _make_profile("profile_b", "Account B", context_id="ctx-b")
        db.list_amazon_login_profiles.return_value = [profile_a, profile_b]

        call_count = 0

        def fake_scrape_one(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
            max_orders_arg: Any,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if profile_arg.profile_key == "profile_b":
                raise RuntimeError("Profile B always fails")
            return {
                "profile_key": profile_arg.profile_key,
                "display_name": profile_arg.display_name,
                "status": "success",
                "orders_created": 2,
                "items_created": 3,
                "message": "ok",
            }

        with patch(
            "transactoid.tools.amazon.scraper._scrape_one_profile",
            side_effect=fake_scrape_one,
        ):
            # act
            result = scrape_amazon_orders(db)

        # assert: mixed outcome -> partial
        assert result["status"] == "partial"
        assert result["profiles_succeeded"] == 1
        assert result["profiles_failed"] == 1
