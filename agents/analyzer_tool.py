from __future__ import annotations

from typing import Any, Callable, Generic, List, Optional, Type, TypeVar, TypedDict

# Note: We avoid importing ORM models to keep this stub dependency-light.

A = TypeVar("A")
S = TypeVar("S")


class AnalyzerSQLRefused(Exception):
    pass


class AnalyzerAnswer(TypedDict):
    """
    Minimal, non-generic TypedDict to satisfy strict typing without external models.
    """

    aggregates: List[object]
    samples: List[object]
    rationales: List[str]


class AnalyzerTool(Generic[A, S]):
    def __init__(
        self,
        *,
        model_name: str = "gpt-5",
        prompt_key_verify: str = "verify-sql",
        prompt_key_nl2sql: str = "nl-to-sql",
    ) -> None:
        self._model_name = model_name
        self._prompt_key_verify = prompt_key_verify
        self._prompt_key_nl2sql = prompt_key_nl2sql

    def verify_sql(
        self,
        sql: str,
        *,
        rationale_out: Optional[List[str]] = None,
    ) -> None:
        """
        LLM second opinion on a SQL string; raises AnalyzerSQLRefused on rejection.
        Stub: always accepts.
        """
        if rationale_out is not None:
            rationale_out.append("stub-accepted")
        return None

    def answer(
        self,
        question: str,
        *,
        aggregate_model: Type[A],
        aggregate_row_factory: Callable[[Any], A],
        sample_model: Type[S],
        sample_pk_column: str = "transaction_id",
        rationale_out: Optional[List[str]] = None,
    ) -> AnalyzerAnswer:
        """
        NL→SQL pipeline. Stub returns empty aggregates and samples with a stub rationale.
        """
        if rationale_out is not None:
            rationale_out.append("stub-executed")
        return {
            "aggregates": [],
            "samples": [],
            "rationales": ["stub"],
        }


