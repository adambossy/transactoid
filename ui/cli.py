from __future__ import annotations

from typing import List, Optional

from agents.transactoid import run as transactoid_run


def sync(access_token: str, cursor: Optional[str] = None, count: int = 500) -> None:
    """
    Sync transactions from Plaid and categorize them using an LLM.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
    """
    return None


def ask(question: str) -> None:
    return None


def recat(merchant_id: int, to: str) -> None:
    return None


def tag(rows: List[int], tags: List[str]) -> None:
    return None


def init_db(url: Optional[str] = None) -> None:
    return None


def seed_taxonomy(yaml_path: str = "configs/taxonomy.yaml") -> None:
    return None


def clear_cache(namespace: str = "default") -> None:
    return None


def agent() -> None:
    """
    Run the transactoid agent to orchestrate sync → categorize → persist in batches.
    """
    transactoid_run()


def _agent_main() -> None:
    """CLI entry point for the agent command."""
    agent()


def main() -> None:
    # Minimal stub entrypoint
    return None


