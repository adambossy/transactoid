"""Schedule selection logic for automated (cron) report runs.

Ported verbatim from the legacy ``transactoid`` CLI
(``services/scheduled_reports.py``). The precedence rule decides which
report prompt key a daily cron run should drive the agent with, based on
New-York wall-clock time:

    annual (Jan 1) > monthly (day 1) > weekly (Sunday) > daily

The returned keys are promptorium prompt keys. Which of them actually exist
in ``backend/.prompts/`` is an independent concern: the cron-manager may pin
explicit ``--prompt-key`` values for the keys it knows are present, and any
missing key surfaces as a normal ``PromptNotFound`` at run time rather than a
silent no-op.
"""

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
    """Pick prompt key with precedence: annual > monthly > weekly > daily.

    The decision is made in New-York local time so a report scheduled for an
    early-morning UTC slot is attributed to the correct local calendar day.
    """
    now = _coerce_utc(now_utc)
    now_ny = now.astimezone(NEW_YORK_TZ)

    if now_ny.month == 1 and now_ny.day == 1:
        return "report-annual"
    if now_ny.day == 1:
        return "report-monthly"
    if now_ny.weekday() == 6:
        return "report-weekly"
    return "report-daily"
