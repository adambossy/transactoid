from __future__ import annotations

from typing import List, Optional, Type, TypeVar

M = TypeVar("M")


class AnalyticsSQLRefused(Exception):
    pass


class AnalyticsTool:
    def __init__(
        self,
        db: "DB",
        *,
        model: Type[M],
        prompt_key_verify: str = "verify-sql",
        max_rows: Optional[int] = None,
    ) -> None:
        self._db = db
        self._model = model
        self._prompt_key_verify = prompt_key_verify
        self._max_rows = max_rows

    def _verify_sql(
        self,
        sql: str,
        *,
        rationale_out: Optional[List[str]] = None,
    ) -> None:
        """
        LLM-based second opinion; raises AnalyticsSQLRefused on rejection.
        Stub: always accepts.
        """
        if rationale_out is not None:
            rationale_out.append("stub-accepted")
        return None

    def _load_verify_prompt(self) -> str:
        # Minimal stub content
        return "verify-sql-stub"

    def _schema_hint(self) -> dict:
        # Minimal stub schema hint
        return {}


