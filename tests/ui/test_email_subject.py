"""Tests for period-specific report email subject formatting."""

from __future__ import annotations

from datetime import datetime

import pytest

from transactoid.ui.cli import _format_report_email_subject

_FALLBACK = "Transactoid Report - {month} {year}"


@pytest.mark.parametrize(
    "prompt_key,now,expected",
    [
        (
            "report-daily",
            datetime(2026, 4, 27),
            "Transactoid Daily Report - April 27, 2026",
        ),
        (
            "report-weekly",
            datetime(2026, 4, 25),
            "Transactoid Weekly Report - April 19-25, 2026",
        ),
        (
            "report-weekly-jenny",
            datetime(2026, 4, 25),
            "Transactoid Weekly Report - April 19-25, 2026",
        ),
        (
            "report-weekly",
            datetime(2026, 4, 3),
            "Transactoid Weekly Report - March 28-April 3, 2026",
        ),
        (
            "report-weekly",
            datetime(2026, 1, 3),
            "Transactoid Weekly Report - December 28, 2025-January 3, 2026",
        ),
        (
            "report-monthly",
            datetime(2026, 4, 1),
            "Transactoid Monthly Report - April 2026",
        ),
        (
            "report-annual",
            datetime(2026, 1, 1),
            "Transactoid Annual Report - 2026",
        ),
        (
            None,
            datetime(2026, 4, 27),
            "Transactoid Report - April 2026",
        ),
        (
            "ad-hoc-question",
            datetime(2026, 4, 27),
            "Transactoid Report - April 2026",
        ),
    ],
)
def test_format_report_email_subject(
    prompt_key: str | None, now: datetime, expected: str
) -> None:
    output = _format_report_email_subject(
        prompt_key=prompt_key, now=now, fallback_template=_FALLBACK
    )

    assert output == expected
