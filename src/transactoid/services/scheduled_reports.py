"""Schedule selection logic for automated report runs."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NEW_YORK_TZ = ZoneInfo("America/New_York")


def _coerce_utc(now_utc: datetime | None) -> datetime:
    """Return an aware UTC datetime for scheduling decisions."""
    if now_utc is None:
        return datetime.now(UTC)

    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=UTC)

    return now_utc.astimezone(UTC)


def select_prompt_key(*, now_utc: datetime | None = None) -> str:
    """Pick prompt key with precedence: annual > monthly > weekly > daily."""
    now = _coerce_utc(now_utc)
    now_ny = now.astimezone(NEW_YORK_TZ)

    if now_ny.month == 1 and now_ny.day == 1:
        return "report-annual"
    if now_ny.day == 1:
        return "report-monthly"
    if now_ny.weekday() == 6:
        return "report-weekly"
    return "report-daily"
