"""Pure aggregation of verdict-enriched eval items into the accuracy trend.

Input is the list of dicts from ``DB.eval_items_with_verdicts`` (each carries the
legacy/agent keys, the derived verdict + human_key, the fast-path flag, and the
version stamp). Output is summary + per-day rows for the trend page.

Honesty rules baked in:
- fast-path rows are excluded from accuracy (verified-reuse, ~100% by construction).
- only *settled* items count (verdict ``corrected`` or ``confirmed``); ``provisional``
  rows are too new to have been reviewed and are reported separately.
- exact-match and parent-level accuracy are tracked separately.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _parent(key: str | None) -> str | None:
    """Parent (top-level) segment of a ``parent.child`` taxonomy key."""
    if not key:
        return None
    return key.split(".", 1)[0]


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy summary over already-filtered (settled, agent-method) rows."""
    reviewed = len(rows)
    if reviewed == 0:
        return {
            "reviewed": 0,
            "corrected": 0,
            "pct_corrected": None,
            "pct_correct_exact": None,
            "pct_correct_parent": None,
            "legacy_pct_correct": None,
            "agent_wins": 0,
            "legacy_wins": 0,
        }
    corrected = sum(1 for r in rows if r["verdict"] == "corrected")
    exact = sum(1 for r in rows if r["human_key"] == r["agent_key"])
    parent = sum(1 for r in rows if _parent(r["human_key"]) == _parent(r["agent_key"]))
    legacy_correct = sum(1 for r in rows if r["human_key"] == r["legacy_key"])
    agent_wins = sum(
        1
        for r in rows
        if r["human_key"] == r["agent_key"] and r["human_key"] != r["legacy_key"]
    )
    legacy_wins = sum(
        1
        for r in rows
        if r["human_key"] == r["legacy_key"] and r["human_key"] != r["agent_key"]
    )
    return {
        "reviewed": reviewed,
        "corrected": corrected,
        "pct_corrected": corrected / reviewed,
        "pct_correct_exact": exact / reviewed,
        "pct_correct_parent": parent / reviewed,
        "legacy_pct_correct": legacy_correct / reviewed,
        "agent_wins": agent_wins,
        "legacy_wins": legacy_wins,
    }


def _accuracy_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Settled, agent-method items — the denominator for accuracy."""
    return [
        it
        for it in items
        if it["method_at_eval_time"] == "agent"
        and it["verdict"] in ("corrected", "confirmed")
    ]


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Overall summary across all runs (settled agent rows), plus coverage counts."""
    summary = _summarize_rows(_accuracy_rows(items))
    summary["provisional"] = sum(1 for it in items if it["verdict"] == "provisional")
    summary["fast_path"] = sum(
        1 for it in items if it["method_at_eval_time"] == "fast_path"
    )
    summary["total_items"] = len(items)
    return summary


def daily_trend(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One summary row per calendar day (by ``run_at``), oldest first.

    Each row carries the version stamp seen that day so the trend page can annotate
    where the categorizer version changed.
    """
    by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    versions: dict[Any, dict[str, Any]] = {}
    for it in items:
        day = it["run_at"].date()
        by_day[day].append(it)
        versions.setdefault(
            day,
            {
                "model": it.get("model"),
                "prompt_version": it.get("prompt_version"),
                "harness_sha": it.get("harness_sha"),
                "taxonomy_version": it.get("taxonomy_version"),
                "rules_version": it.get("rules_version"),
            },
        )
    out: list[dict[str, Any]] = []
    for day in sorted(by_day):
        day_items = by_day[day]
        row = {"date": day.isoformat(), "version": versions[day]}
        row.update(_summarize_rows(_accuracy_rows(day_items)))
        out.append(row)
    return out
