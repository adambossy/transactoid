"""Tests for scheduled report selection logic."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from transactoid.services.scheduled_reports import select_prompt_key, should_run_now


@pytest.mark.parametrize(
    ("input_now", "expected_output"),
    [
        # Jan 1 at 5 AM New York (10:00 UTC in standard time) -> annual
        (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), "report-annual"),
        # First of month (not Jan 1) at 5 AM New York -> monthly
        (datetime(2026, 2, 1, 10, 0, tzinfo=UTC), "report-monthly"),
        # Sunday (not first of month) at 5 AM New York -> weekly
        (datetime(2026, 2, 8, 10, 0, tzinfo=UTC), "report-weekly"),
        # Normal weekday at 5 AM New York -> daily
        (datetime(2026, 2, 3, 10, 0, tzinfo=UTC), "report-daily"),
    ],
)
def test_select_prompt_key_returns_expected_prompt(
    input_now: datetime, expected_output: str
) -> None:
    # act
    output = select_prompt_key(now_utc=input_now)

    # assert
    assert output == expected_output


@pytest.mark.parametrize(
    ("input_now", "expected_output"),
    [
        # EST window
        (datetime(2026, 2, 16, 10, 0, tzinfo=UTC), True),
        # EDT window
        (datetime(2026, 6, 16, 9, 0, tzinfo=UTC), True),
        # Not 5 AM New York
        (datetime(2026, 2, 16, 9, 0, tzinfo=UTC), False),
    ],
)
def test_should_run_now_matches_new_york_5am(
    input_now: datetime, expected_output: bool
) -> None:
    # act
    output = should_run_now(now_utc=input_now)

    # assert
    assert output == expected_output
