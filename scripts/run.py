from __future__ import annotations


def run_sync(
    *,
    access_token: str,
    cursor: str | None = None,
    count: int = 500,
) -> None:
    """
    Sync transactions from Plaid and categorize them using an LLM.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
    """
    return None


def run_pipeline(
    *,
    access_token: str,
    cursor: str | None = None,
    count: int = 500,
    questions: list[str] | None = None,
) -> None:
    """
    Run the full pipeline: sync → categorize → persist.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
        questions: Optional questions for analytics
    """
    return None
