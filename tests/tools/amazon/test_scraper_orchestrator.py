"""Tests for the scrape_amazon_orders orchestrator flow."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from transactoid.adapters.db.facade import DB
from transactoid.tools.amazon.scraper import (
    ScrapedItem,
    ScrapedOrder,
    _aggregate_results,
    _resolve_effective_since,
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
    profile_id: int = 1,
    history_complete_through: date | None = None,
) -> MagicMock:
    """Build a mock AmazonLoginProfileDB with sensible defaults."""
    profile = MagicMock()
    profile.profile_key = profile_key
    profile.display_name = display_name
    profile.browserbase_context_id = context_id
    profile.profile_id = profile_id
    profile.history_complete_through = history_complete_through
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
    def test_scrape_profile_with_retry_does_not_retry(self) -> None:
        # Why: Browserbase sessions are paid-per-minute and a fresh session
        # restarts iteration from page 1, re-extracting rows already persisted.
        # The orchestrator now persists partial results and returns immediately.
        # input
        db = MagicMock()
        profile = _make_profile(context_id="ctx-abc")
        call_count = 0

        def fake_scrape_one(
            db_arg: Any,
            profile_arg: Any,
            backend_arg: Any,
            max_orders_arg: Any,
            since_arg: Any,
            until_arg: Any,
            is_unbounded_request_arg: Any,
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Transient failure")

        with patch(
            "transactoid.tools.amazon.scraper._scrape_one_profile",
            side_effect=fake_scrape_one,
        ):
            # act
            result = _scrape_profile_with_retry(
                db, profile, "stagehand-browserbase", None, None, None, True
            )

        # assert
        assert call_count == 1
        assert result["status"] == "error"
        assert "Transient failure" in result["message"]

    def test_scrape_profile_with_retry_returns_error_on_failure(
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
                db, profile, "stagehand-browserbase", None, None, None, True
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
            since_arg: Any,
            until_arg: Any,
            is_unbounded_request_arg: Any,
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
            _scrape_profile_with_retry(
                db, profile, "stagehand-browserbase", None, None, None, True
            )

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

    def test_scrape_amazon_orders_attributes_orders_to_originating_profile(
        self,
    ) -> None:
        # input
        db = MagicMock()
        profile_a = _make_profile(
            "profile_a", "Account A", context_id="ctx-a", profile_id=11
        )
        profile_b = _make_profile(
            "profile_b", "Account B", context_id="ctx-b", profile_id=22
        )
        db.list_amazon_login_profiles.return_value = [profile_a, profile_b]

        order_a = ScrapedOrder(
            order_id="order-a",
            order_date="2024-01-15",
            order_total_cents=1000,
            tax_cents=80,
            shipping_cents=0,
            items=[],
        )
        order_b = ScrapedOrder(
            order_id="order-b",
            order_date="2024-01-16",
            order_total_cents=2000,
            tax_cents=160,
            shipping_cents=0,
            items=[],
        )

        scraped_by_context = {"ctx-a": [order_a], "ctx-b": [order_b]}

        def fake_get_backend(
            backend_name: Any, *, context_id: Any, login_mode: Any
        ) -> MagicMock:
            backend = MagicMock()
            backend.scrape_order_history.return_value = scraped_by_context[context_id]
            return backend

        with patch(
            "transactoid.tools.amazon.scraper._get_backend",
            side_effect=fake_get_backend,
        ):
            # act
            scrape_amazon_orders(db)

        # assert: each upsert_amazon_order call carries its originating profile_id
        upsert_calls = db.upsert_amazon_order.call_args_list
        attribution = {
            call.kwargs["order_id"]: call.kwargs["profile_id"] for call in upsert_calls
        }
        assert attribution == {"order-a": 11, "order-b": 22}

    def test_scrape_amazon_orders_forwards_since_until_to_backend(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db, since=date(2025, 1, 1), until=date(2025, 12, 31))

        # assert: backend received the date window verbatim (no DB floor).
        mock_backend.scrape_order_history.assert_called_once_with(
            since=date(2025, 1, 1), until=date(2025, 12, 31), max_orders=None
        )

    def test_scrape_amazon_orders_uses_db_floor_when_no_since(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = date(2024, 6, 15)
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db)

        # assert: backend received the DB floor as `since`.
        kwargs = mock_backend.scrape_order_history.call_args.kwargs
        assert kwargs["since"] == date(2024, 6, 15)
        assert kwargs["until"] is None

    def test_scrape_amazon_orders_db_floor_supersedes_earlier_user_since(
        self,
    ) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = date(2024, 6, 15)
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db, since=date(2020, 1, 1))

        # assert: tighter DB floor wins over user-supplied --since.
        kwargs = mock_backend.scrape_order_history.call_args.kwargs
        assert kwargs["since"] == date(2024, 6, 15)

    def test_scrape_amazon_orders_user_since_wins_when_tighter_than_db_floor(
        self,
    ) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = date(2020, 1, 1)
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db, since=date(2025, 6, 1))

        # assert: user --since (2025-06-01) is tighter than DB floor.
        kwargs = mock_backend.scrape_order_history.call_args.kwargs
        assert kwargs["since"] == date(2025, 6, 1)

    def test_scrape_amazon_orders_warns_when_db_floor_is_none(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(context_id="ctx-existing")
        db.list_amazon_login_profiles.return_value = [profile]

        warnings: list[str] = []

        def capture_warning(msg: str, *args: Any, **kwargs: Any) -> None:
            warnings.append(msg)

        with (
            patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend,
            patch(
                "transactoid.tools.amazon.scraper.logger.warning",
                side_effect=capture_warning,
            ),
        ):
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db)

        # assert: warning emitted and backend received `since=None`.
        assert any("No plaid_transactions" in w for w in warnings)
        kwargs = mock_backend.scrape_order_history.call_args.kwargs
        assert kwargs["since"] is None


# ---------------------------------------------------------------------------
# scrape_amazon_orders — profile_key filter
# ---------------------------------------------------------------------------


class TestScrapeAmazonOrdersProfileKeyFilter:
    def test_scrape_amazon_orders_profile_key_scrapes_only_matching_profile(
        self,
    ) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        adam = _make_profile(
            profile_key="adam@x.com",
            display_name="Adam",
            context_id="ctx-adam",
            profile_id=1,
        )
        jenny = _make_profile(
            profile_key="jenny@x.com",
            display_name="Jenny",
            context_id="ctx-jenny",
            profile_id=2,
        )
        db.list_amazon_login_profiles.return_value = [adam, jenny]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.return_value = []
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db, profile_key="jenny@x.com")

        # assert: only Jenny was scraped
        assert result["status"] == "success"
        assert result["profiles_total"] == 1
        scraped_keys = [pr["profile_key"] for pr in result["profile_results"]]
        assert scraped_keys == ["jenny@x.com"]

    def test_scrape_amazon_orders_unknown_profile_key_returns_error(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_key="adam@x.com", context_id="ctx-adam")
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        result = scrape_amazon_orders(db, profile_key="missing@x.com")

        # assert
        assert result["status"] == "error"
        assert "missing@x.com" in result["message"]
        assert result["profiles_total"] == 0


# ---------------------------------------------------------------------------
# _resolve_effective_since
# ---------------------------------------------------------------------------


class TestResolveEffectiveSince:
    def test_resolve_effective_since_both_none(self) -> None:
        assert _resolve_effective_since(None, None) is None

    def test_resolve_effective_since_only_user(self) -> None:
        assert _resolve_effective_since(date(2024, 1, 1), None) == date(2024, 1, 1)

    def test_resolve_effective_since_only_db_floor(self) -> None:
        assert _resolve_effective_since(None, date(2024, 1, 1)) == date(2024, 1, 1)

    def test_resolve_effective_since_db_floor_tighter_wins(self) -> None:
        assert _resolve_effective_since(date(2020, 1, 1), date(2024, 6, 15)) == date(
            2024, 6, 15
        )

    def test_resolve_effective_since_user_tighter_wins(self) -> None:
        assert _resolve_effective_since(date(2025, 6, 1), date(2020, 1, 1)) == date(
            2025, 6, 1
        )

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
            since_arg: Any,
            until_arg: Any,
            is_unbounded_request_arg: Any,
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


# ---------------------------------------------------------------------------
# scrape_amazon_orders — history_complete_through watermark
# ---------------------------------------------------------------------------


class TestHistoryCompleteThroughWatermark:
    def _patched_scrape(
        self,
        db: MagicMock,
        backend_orders: list[ScrapedOrder] | None = None,
        backend_side_effect: Exception | None = None,
        **scrape_kwargs: Any,
    ) -> tuple[dict[str, Any], MagicMock]:
        """Run scrape_amazon_orders with backend mocked. Returns (result, backend)."""
        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            if backend_side_effect is not None:
                mock_backend.scrape_order_history.side_effect = backend_side_effect
                mock_backend.collected_orders = []
            else:
                mock_backend.scrape_order_history.return_value = backend_orders or []
            mock_get_backend.return_value = mock_backend
            result = scrape_amazon_orders(db, **scrape_kwargs)
        return result, mock_backend

    def test_scrape_amazon_orders_writes_watermark_on_unbounded_success(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        self._patched_scrape(db, backend_orders=_make_scraped_orders(1))

        # assert
        db.set_amazon_profile_history_watermark.assert_called_once_with(
            profile_id=42, through_date=date.today()
        )

    def test_scrape_amazon_orders_skips_watermark_when_since_provided(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        self._patched_scrape(
            db, backend_orders=_make_scraped_orders(1), since=date(2025, 1, 1)
        )

        # assert
        db.set_amazon_profile_history_watermark.assert_not_called()

    def test_scrape_amazon_orders_skips_watermark_when_until_provided(self) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        self._patched_scrape(
            db, backend_orders=_make_scraped_orders(1), until=date(2025, 12, 31)
        )

        # assert
        db.set_amazon_profile_history_watermark.assert_not_called()

    def test_scrape_amazon_orders_skips_watermark_when_max_orders_provided(
        self,
    ) -> None:
        # input
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        self._patched_scrape(db, backend_orders=_make_scraped_orders(1), max_orders=5)

        # assert
        db.set_amazon_profile_history_watermark.assert_not_called()

    def test_scrape_amazon_orders_skips_watermark_on_partial(self) -> None:
        # input — backend raises mid-scrape with prior collected orders
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.side_effect = RuntimeError("mid-flight")
            mock_backend.collected_orders = _make_scraped_orders(1)
            mock_get_backend.return_value = mock_backend

            # act
            result = scrape_amazon_orders(db)

        # assert
        assert result["profile_results"][0]["status"] == "partial"
        db.set_amazon_profile_history_watermark.assert_not_called()

    def test_scrape_amazon_orders_skips_watermark_on_error(self) -> None:
        # input — backend raises with no prior collected orders
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = None
        profile = _make_profile(profile_id=42, context_id="ctx")
        db.list_amazon_login_profiles.return_value = [profile]

        with patch("transactoid.tools.amazon.scraper._get_backend") as mock_get_backend:
            mock_backend = MagicMock()
            mock_backend.scrape_order_history.side_effect = RuntimeError("dead")
            mock_backend.collected_orders = []
            mock_get_backend.return_value = mock_backend

            # act
            scrape_amazon_orders(db)

        # assert
        db.set_amazon_profile_history_watermark.assert_not_called()

    def test_scrape_amazon_orders_uses_profile_watermark_as_floor(self) -> None:
        # input — DB floor is 2024-01-09, profile watermark is 2026-01-01
        db = MagicMock()
        db.min_plaid_transaction_date.return_value = date(2024, 1, 9)
        profile = _make_profile(
            profile_id=42,
            context_id="ctx",
            history_complete_through=date(2026, 1, 1),
        )
        db.list_amazon_login_profiles.return_value = [profile]

        # act
        _, mock_backend = self._patched_scrape(db, backend_orders=[])

        # assert: backend received the profile watermark (tighter than DB floor)
        mock_backend.scrape_order_history.assert_called_once_with(
            since=date(2026, 1, 1), until=None, max_orders=None
        )
