"""SQL query tool for executing raw SQL queries against the transaction database."""

from __future__ import annotations

from typing import Any

from transactoid.infra.db.facade import DB
from transactoid.tools.base import StandardTool
from transactoid.tools.protocol import ToolInputSchema


class RunSQLTool(StandardTool):
    """
    Tool for executing SQL queries against the transaction database.

    Exposes DB.execute_raw_sql through the standardized Tool protocol.
    Returns rows as list of dictionaries with JSON-serializable values.
    """

    _name = "run_sql"
    _description = (
        "Execute SQL queries against the transaction database. "
        "Returns rows as list of dictionaries. "
        "Useful for answering natural language questions about finances."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL query string to execute",
            },
        },
        "required": ["query"],
    }

    def __init__(self, db: DB) -> None:
        """
        Initialize the SQL query tool.

        Args:
            db: Database instance
        """
        self._db = db

    def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query string

        Returns:
            JSON-serializable dict with:
            - status: "success" or "error"
            - rows: List of dicts (one per row) if query returns rows
            - count: Number of rows returned or affected
            - error: Error message if status is "error"
        """
        query: str = kwargs["query"]

        try:
            result = self._db.execute_raw_sql(query)

            if result.returns_rows:
                # Convert Row objects to dicts
                rows = [dict(row._mapping) for row in result.fetchall()]

                # Convert date/datetime objects to ISO format strings
                for row in rows:
                    for key, value in row.items():
                        if hasattr(value, "isoformat"):
                            row[key] = value.isoformat()

                return {
                    "status": "success",
                    "rows": rows,
                    "count": len(rows),
                }
            else:
                # Non-SELECT query (INSERT, UPDATE, DELETE, etc.)
                return {
                    "status": "success",
                    "rows": [],
                    "count": result.rowcount,
                }
        except Exception as e:
            return {
                "status": "error",
                "rows": [],
                "count": 0,
                "error": str(e),
            }
