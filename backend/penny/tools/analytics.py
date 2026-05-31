"""Analytics — direct SQL access for the agent.

Mirrors the original ``run_sql`` MCP tool: arbitrary SQL against the
shared DB, dates/datetimes ISO-stringified for JSON safety. Per the
explicit project decision, the tool stays **unrestricted** in this MVP
(read AND write SQL both pass through). Tightening this is a
productionization item, not a port-time concern.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from ..db import get_db
from ..tools._services.chart import GenerateChartTool


def _serialize_row(row: Any) -> dict[str, Any]:
    out = dict(row._mapping)
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


@tool
async def run_sql(query: str) -> dict[str, Any]:
    """Execute a SQL query against the Penny transaction database.

    Use ``SELECT`` for analytics; the database also accepts mutations but
    prefer the dedicated tools (recategorize, tag, migrate-taxonomy) when
    they exist for what you want to do.

    Args:
        query: SQL statement to execute.

    Returns:
        ``{"status": "success", "rows": [...], "count": N}`` on success;
        ``{"status": "error", "rows": [], "count": 0, "error": str}`` on
        failure.
    """

    def _run() -> dict[str, Any]:
        try:
            result = get_db().execute_raw_sql(query)
            if result.returns_rows:
                rows = [_serialize_row(row) for row in result.fetchall()]
                return {"status": "success", "rows": rows, "count": len(rows)}
            return {"status": "success", "rows": [], "count": result.rowcount}
        except Exception as exc:
            return {"status": "error", "rows": [], "count": 0, "error": str(exc)}

    return await asyncio.to_thread(_run)


@tool
async def generate_chart(
    chart_type: str,
    title: str,
    data: dict[str, float],
    x_label: str = "",
    y_label: str = "",
) -> dict[str, Any]:
    """Generate a chart and return base64 PNG, file path, and an ASCII plot.

    Args:
        chart_type: ``"bar"``, ``"line"``, or ``"pie"``.
        title: Chart title.
        data: Label-to-number mapping, e.g. ``{"Groceries": 450.0}``.
        x_label: Optional x-axis label.
        y_label: Optional y-axis label.
    """
    chart = GenerateChartTool()
    return await chart.execute(
        chart_type=chart_type,
        title=title,
        data=data,
        x_label=x_label,
        y_label=y_label,
    )
