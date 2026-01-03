"""Logging for Amazon matching operations.

Separates logging logic from business logic per AGENTS.md guidelines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import loguru
from loguru import logger

if TYPE_CHECKING:
    from transactoid.adapters.amazon.plaid_matcher import MatchingReport, NoMatchReason


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

    def matching_complete(self, report: MatchingReport) -> None:
        """Log matching completion summary."""
        if report.total_amazon_transactions == 0:
            self._logger.info("No Amazon transactions to match")
            return

        match_rate = report.matched_count / report.total_amazon_transactions * 100

        self._logger.bind(
            matched=report.matched_count,
            unmatched=report.unmatched_count,
            total=report.total_amazon_transactions,
            match_rate=match_rate,
        ).info(
            "Amazon matching complete: {}/{} matched ({:.1f}%)",
            report.matched_count,
            report.total_amazon_transactions,
            match_rate,
        )

        # Log failure reason breakdown
        if report.failure_reasons:
            for reason, count in report.failure_reasons.items():
                self._logger.bind(reason=reason.value, count=count).debug(
                    "  {} unmatched: {}", count, reason.value
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

    def no_match(
        self,
        plaid_id: int,
        reason: NoMatchReason,
        amount_cents: int,
    ) -> None:
        """Log unmatched Amazon transaction."""
        self._logger.bind(
            plaid_id=plaid_id,
            reason=reason.value,
            amount_cents=amount_cents,
        ).debug(
            "No match for plaid_txn {} (${:.2f}): {}",
            plaid_id,
            amount_cents / 100,
            reason.value,
        )

    def item_reconciled(
        self,
        order_id: str,
        asin: str,
        description: str,
        plaid_id: int,
    ) -> None:
        """Log item reconciled to Plaid transaction."""
        self._logger.bind(
            order_id=order_id,
            asin=asin,
            plaid_id=plaid_id,
        ).debug(
            "Item {} ({}) reconciled to plaid_txn {}",
            asin,
            description[:30],
            plaid_id,
        )

    def item_unreconciled(
        self,
        order_id: str,
        asin: str,
        description: str,
    ) -> None:
        """Log item not reconciled."""
        self._logger.bind(
            order_id=order_id,
            asin=asin,
        ).debug(
            "Item {} ({}) not reconciled - order unmatched",
            asin,
            description[:30],
        )
