"""Unit tests for the Stagehand Browserbase backend helpers."""

from __future__ import annotations

from datetime import date

from transactoid.tools.amazon.backends.stagehand_browserbase import (
    _page_url,
    _years_for_window,
)

BASE_URL = "https://www.amazon.com/your-orders/orders"

TODAY = date(2026, 4, 19)


def test_years_for_window_no_constraints_returns_default_view_marker() -> None:
    output = _years_for_window(since=None, until=None, max_orders=None, today=TODAY)
    assert output == [None]


def test_years_for_window_only_since_includes_floor_year() -> None:
    output = _years_for_window(
        since=date(2023, 6, 15), until=None, max_orders=None, today=TODAY
    )
    assert output == [2026, 2025, 2024, 2023]


def test_years_for_window_only_until_back_to_floor_years() -> None:
    output = _years_for_window(
        since=None,
        until=date(2024, 12, 31),
        max_orders=None,
        today=TODAY,
        floor_years=20,
    )
    assert output[0] == 2024
    assert output[-1] == TODAY.year - 20
    years_only = [year for year in output if year is not None]
    assert years_only == sorted(years_only, reverse=True)


def test_years_for_window_both_bounds_inclusive() -> None:
    output = _years_for_window(
        since=date(2024, 3, 1),
        until=date(2025, 9, 30),
        max_orders=None,
        today=TODAY,
    )
    assert output == [2025, 2024]


def test_years_for_window_single_year_window() -> None:
    output = _years_for_window(
        since=date(2025, 1, 1),
        until=date(2025, 12, 31),
        max_orders=None,
        today=TODAY,
    )
    assert output == [2025]


def test_years_for_window_since_after_until_returns_empty() -> None:
    output = _years_for_window(
        since=date(2025, 1, 1),
        until=date(2024, 12, 31),
        max_orders=None,
        today=TODAY,
    )
    assert output == []


def test_years_for_window_until_clamped_to_today() -> None:
    output = _years_for_window(
        since=date(2025, 1, 1),
        until=date(2030, 12, 31),
        max_orders=None,
        today=TODAY,
    )
    # Future `until` is clamped to today's year — Amazon has no future orders.
    assert output == [2026, 2025]


def test_page_url_default_view_page_one_returns_base_url() -> None:
    assert _page_url(BASE_URL, year_filter=None, page_num=1) == BASE_URL


def test_page_url_default_view_page_three_appends_start_index() -> None:
    output = _page_url(BASE_URL, year_filter=None, page_num=3)
    assert output == f"{BASE_URL}?startIndex=20"


def test_page_url_year_filter_page_one_omits_start_index() -> None:
    output = _page_url(BASE_URL, year_filter=2025, page_num=1)
    assert output == f"{BASE_URL}?timeFilter=year-2025"


def test_page_url_year_filter_page_seven_combines_both_params() -> None:
    output = _page_url(BASE_URL, year_filter=2024, page_num=7)
    assert output == f"{BASE_URL}?timeFilter=year-2024&startIndex=60"


def test_years_for_window_max_orders_only_iterates_floor_years() -> None:
    output = _years_for_window(
        since=None,
        until=None,
        max_orders=5,
        today=TODAY,
        floor_years=3,
    )
    # max_orders alone disables the [None] default-view branch.
    assert output == [2026, 2025, 2024, 2023]
