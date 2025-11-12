from __future__ import annotations

from typing import List, Optional, Sequence


def run_categorizer(
    *,
    mode: str,
    data_dir: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
) -> None:
    return None


def run_analyzer(
    *,
    questions: Optional[List[str]] = None,
) -> None:
    return None


def run_pipeline(
    *,
    mode: str,
    data_dir: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
    questions: Optional[List[str]] = None,
) -> None:
    return None
