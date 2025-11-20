from __future__ import annotations

import argparse
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


def agent(
    *,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
) -> None:
    """
    Run the transactoid agent to orchestrate sync → categorize → persist in batches.

    Args:
        batch_size: Number of transactions to process per batch
        confidence_threshold: Minimum confidence score for categorization
    """
    transactoid_run(batch_size=batch_size, confidence_threshold=confidence_threshold)


def _agent_main(argv: list[str] | None = None) -> None:
    """CLI entry point for the agent command."""
    parser = argparse.ArgumentParser(
        description="Run the transactoid agent to orchestrate sync → categorize → persist in batches.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Number of transactions to process per batch (default: 25)",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.70,
        help="Minimum confidence score for categorization (default: 0.70)",
    )
    args = parser.parse_args(argv)
    agent(batch_size=args.batch_size, confidence_threshold=args.confidence_threshold)


def main() -> None:
    # Minimal stub entrypoint
    return None


