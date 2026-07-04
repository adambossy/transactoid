"""Analytics — direct SQL access for the agent.

Mirrors the original ``run_sql`` MCP tool: arbitrary SQL, dates/datetimes
ISO-stringified for JSON safety. As of phase 2 the free-form SQL path runs on a
**read-only** DB role (``get_readonly_db``) under the request's tenant context
(``session_for``), so RLS still fences reads and the database itself rejects any
prompt-injected write. Curated ``@tool`` writes keep a normal read-write
connection.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from agent_harness import tool
from sqlalchemy import text

from penny.db import get_readonly_db
from penny.tenancy.context import require_request_context
from penny.tools._services.chart import GenerateChartTool


def _serialize_row(row: Any) -> dict[str, Any]:
    """Make a SQL result row JSON-native.

    Postgres ``numeric`` columns arrive as ``Decimal`` — convert to float so
    tool output stays a number (json.dumps would otherwise raise, and
    ``default=str`` would silently turn amounts into strings).
    """
    out = dict(row._mapping)
    for key, value in out.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


@tool
async def run_sql(query: str) -> dict[str, Any]:
    """Execute a read-only SQL query against the Penny transaction database.

    Use ``SELECT`` for analytics. This path runs on a read-only role, so writes
    are rejected — use the dedicated tools (recategorize, tag, migrate-taxonomy)
    to change data.

    Args:
        query: SQL statement to execute.

    Returns:
        ``{"status": "success", "rows": [...], "count": N}`` on success;
        ``{"status": "error", "rows": [], "count": 0, "error": str}`` on
        failure.
    """

    def _run() -> dict[str, Any]:
        try:
            # session_for pins the tenant GUCs so RLS scopes the read; the
            # read-only role blocks any DML at the database level.
            ctx = require_request_context()
            with get_readonly_db().session_for(ctx) as session:
                result = session.execute(text(query))
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
