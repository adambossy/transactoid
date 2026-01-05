"""Logging for Amazon matching operations.

Separates logging logic from business logic per AGENTS.md guidelines.
"""

from __future__ import annotations

import loguru
from loguru import logger



class AmazonMatcherLogger:
    """Handles all logging for Amazon matching with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        """Initialize logger.

        Args:
            logger_instance: Logger instance to use (defaults to loguru.logger)
        """
        self._logger = logger_instance

    def index_loaded(self, order_count: int, item_count: int) -> None:
        """Log Amazon index loaded."""
        self._logger.bind(orders=order_count, items=item_count).info(
            "Amazon order index loaded: {} orders, {} items",
            order_count,
            item_count,
        )

    def matching_start(self, amazon_txn_count: int, total_txn_count: int) -> None:
        """Log start of matching process."""
        self._logger.bind(
            amazon_count=amazon_txn_count, total_count=total_txn_count
        ).info(
            "Matching {} Amazon transactions (of {} total)",
            amazon_txn_count,
            total_txn_count,
        )

    def match_found(
        self,
        plaid_id: int,
        order_id: str,
        item_count: int,
        amount_cents: int,
    ) -> None:
        """Log individual match found."""
        self._logger.bind(
            plaid_id=plaid_id,
            order_id=order_id,
            items=item_count,
            amount_cents=amount_cents,
        ).debug(
            "Matched plaid_txn {} -> order {} ({} items, ${:.2f})",
            plaid_id,
            order_id,
            item_count,
            amount_cents / 100,
        )

    def split_created(
        self,
        plaid_id: int,
        derived_count: int,
        external_ids: list[str],
    ) -> None:
        """Log derived transaction split created."""
        self._logger.bind(
            plaid_id=plaid_id,
            derived_count=derived_count,
            external_ids=external_ids,
        ).debug(
            "Created {} derived transactions from plaid_txn {}",
            derived_count,
            plaid_id,
        )

