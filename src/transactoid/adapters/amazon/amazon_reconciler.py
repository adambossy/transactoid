"""Amazon transaction reconciliation and splitting logic."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import loguru
from loguru import logger

from transactoid.adapters.amazon.csv_loader import (
    AmazonItemsCSVLoader,
    AmazonOrdersCSVLoader,
    CSVOrder,
)
from transactoid.adapters.db.models import (
    DerivedTransaction,
    PlaidTransaction,
    normalize_merchant_name,
)


class AmazonReconcilerLogger:
    """Handles logging for Amazon reconciliation with formatting logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance
        self._csv_logged_dirs: set[str] = set()

    def csv_loaded(
        self,
        orders: dict[str, CSVOrder],
        items_count: int,
        csv_dir: Path,
    ) -> None:
        """Log CSV load summary once per directory."""
        csv_dir_str = str(csv_dir)
        if csv_dir_str in self._csv_logged_dirs:
            return
        self._csv_logged_dirs.add(csv_dir_str)

        if orders:
            order_dates = [o.order_date for o in orders.values()]
            min_date = min(order_dates)
            max_date = max(order_dates)
            self._logger.info(
                "Loaded {} Amazon orders ({} to {}) and {} orders with items from {}",
                len(orders),
                min_date,
                max_date,
                items_count,
                csv_dir,
            )
        else:
            self._logger.warning("No Amazon orders loaded from {}", csv_dir)

    def match_attempt(
        self,
        external_id: str,
        amount_cents: int,
        posted_at: date,
        order_count: int,
    ) -> None:
        """Log the start of a match attempt."""
        self._logger.debug(
            "Matching Plaid txn {}: amount=${:.2f}, date={}, searching {} orders",
            external_id,
            amount_cents / 100,
            posted_at,
            order_count,
        )

    def match_found(
        self,
        external_id: str,
        order: CSVOrder,
        date_diff: int,
    ) -> None:
        """Log successful match."""
        self._logger.debug(
            "Found match for {}: order={}, amt=${:.2f}, date={}, diff={}d",
            external_id,
            order.order_id,
            order.order_total_cents / 100,
            order.order_date,
            date_diff,
        )

    def near_misses_found(
        self,
        amount_cents: int,
        posted_at: date,
        near_misses: list[tuple[CSVOrder, int, int, str]],
    ) -> None:
        """Log near-miss orders that were close but didn't match."""
        top_misses = near_misses[:3]
        miss_details = self._format_near_misses(top_misses)
        self._logger.info(
            "Near misses for ${:.2f} on {}: {}",
            amount_cents / 100,
            posted_at,
            miss_details,
        )

    def no_near_misses(
        self,
        amount_cents: int,
        posted_at: date,
        order_count: int,
    ) -> None:
        """Log when no near misses were found."""
        self._logger.info(
            "No near misses for ${:.2f} on {} (checked {} orders)",
            amount_cents / 100,
            posted_at,
            order_count,
        )

    def no_order_match(
        self,
        external_id: str,
        amount_cents: int,
        posted_at: date,
    ) -> None:
        """Log when no order match is found for a transaction."""
        self._logger.warning(
            "No Amazon order match for Plaid transaction {} (${:.2f} on {})",
            external_id,
            amount_cents / 100,
            posted_at,
        )

    def no_items_for_order(self, order_id: str) -> None:
        """Log when an order has no items."""
        self._logger.error("No items found for Amazon order {}", order_id)

    def enrichment_multiple_matches(self, amount_cents: int) -> None:
        """Log when multiple old transactions match by amount."""
        self._logger.warning(
            "Multiple old txns with amount {}, matched first", amount_cents
        )

    def enrichment_no_available_match(self, amount_cents: int) -> None:
        """Log when all candidates for an amount are already matched."""
        self._logger.info(
            "No match for amount {} (all candidates matched)", amount_cents
        )

    def enrichment_no_old_transaction(self, amount_cents: int) -> None:
        """Log when no old transaction exists for an amount."""
        self._logger.info(
            "No old transaction found with amount {}, using fresh data", amount_cents
        )

    def enrichment_unmatched_old(self, count: int, amounts: list[int]) -> None:
        """Log unmatched old transactions."""
        self._logger.warning(
            "Unmatched old transactions: {} with amounts {}", count, amounts
        )

    def _format_near_misses(self, misses: list[tuple[CSVOrder, int, int, str]]) -> str:
        """Format near-miss details for logging."""
        return "; ".join(
            f"{o.order_id} (${o.order_total_cents / 100:.2f} {o.order_date}): {reason}"
            for o, _, _, reason in misses
        )


# Module-level logger instance
_reconciler_logger = AmazonReconcilerLogger()


def is_amazon_transaction(merchant_descriptor: str | None) -> bool:
    """Check if a transaction is from Amazon.

    Args:
        merchant_descriptor: Merchant descriptor from Plaid

    Returns:
        True if transaction is from Amazon
    """
    if not merchant_descriptor:
        return False

    normalized = normalize_merchant_name(merchant_descriptor)
    patterns = ["amazon", "amzn", "amazon.com", "amazon marketplace", "prime video"]
    return any(pattern in normalized for pattern in patterns)


def _build_mismatch_reason(
    amount_diff: int,
    date_diff: int,
    amount_tolerance: int,
    date_tolerance: int,
) -> str:
    """Build a human-readable reason for why a match failed."""
    if amount_diff > amount_tolerance and date_diff > date_tolerance:
        return (
            f"amt={amount_diff}c (>{amount_tolerance}c), "
            f"date={date_diff}d (>{date_tolerance}d)"
        )
    elif amount_diff > amount_tolerance:
        return f"amt={amount_diff}c (>{amount_tolerance}c)"
    else:
        return f"date={date_diff}d (>{date_tolerance}d)"


def find_matching_amazon_order(
    plaid_txn: PlaidTransaction,
    orders: dict[str, CSVOrder],
    date_tolerance_days: int = 3,
    amount_tolerance_cents: int = 50,
    *,
    reconciler_logger: AmazonReconcilerLogger = _reconciler_logger,
) -> CSVOrder | None:
    """Find Amazon order matching Plaid transaction.

    Match criteria:
    - Amount within tolerance
    - Date within tolerance
    - Return best match by date proximity

    Args:
        plaid_txn: Plaid transaction to match
        orders: Dictionary of Amazon orders (order_id -> CSVOrder)
        date_tolerance_days: Maximum date difference in days (default: 3)
        amount_tolerance_cents: Maximum amount difference in cents (default: 50)
        reconciler_logger: Logger instance for diagnostic output

    Returns:
        Best matching CSVOrder or None if no match found
    """
    plaid_amount = abs(plaid_txn.amount_cents)
    plaid_date = plaid_txn.posted_at

    reconciler_logger.match_attempt(
        plaid_txn.external_id, plaid_amount, plaid_date, len(orders)
    )

    candidates: list[tuple[CSVOrder, int]] = []
    near_misses: list[tuple[CSVOrder, int, int, str]] = []

    for order in orders.values():
        amount_diff = abs(plaid_amount - order.order_total_cents)
        date_diff = abs((plaid_date - order.order_date).days)

        if amount_diff <= amount_tolerance_cents and date_diff <= date_tolerance_days:
            candidates.append((order, date_diff))
        elif date_diff <= 30 and amount_diff <= 5000:
            reason = _build_mismatch_reason(
                amount_diff, date_diff, amount_tolerance_cents, date_tolerance_days
            )
            near_misses.append((order, amount_diff, date_diff, reason))

    if candidates:
        best = min(candidates, key=lambda x: x[1])
        reconciler_logger.match_found(plaid_txn.external_id, best[0], best[1])
        return best[0]

    # No match - log diagnostics
    if near_misses:
        near_misses.sort(key=lambda x: x[1] + x[2] * 100)
        reconciler_logger.near_misses_found(plaid_amount, plaid_date, near_misses)
    else:
        reconciler_logger.no_near_misses(plaid_amount, plaid_date, len(orders))

    return None


def create_split_derived_transactions(
    plaid_txn: PlaidTransaction,
    csv_dir: Path,
    *,
    reconciler_logger: AmazonReconcilerLogger = _reconciler_logger,
) -> list[dict[str, Any]]:
    """Create split derived transactions from Amazon order.

    Allocates tax and shipping proportionally based on item subtotals.

    Args:
        plaid_txn: Plaid transaction to split
        csv_dir: Directory containing Amazon CSV files
        reconciler_logger: Logger instance for diagnostic output

    Returns:
        List of derived transaction data dictionaries
    """
    orders_csv = csv_dir / "amazon-order-history-orders.csv"
    items_csv = csv_dir / "amazon-order-history-items.csv"
    orders = AmazonOrdersCSVLoader(orders_csv).load()
    items_by_order = AmazonItemsCSVLoader(items_csv).load()

    reconciler_logger.csv_loaded(orders, len(items_by_order), csv_dir)

    order = find_matching_amazon_order(
        plaid_txn, orders, reconciler_logger=reconciler_logger
    )
    if not order:
        reconciler_logger.no_order_match(
            plaid_txn.external_id,
            abs(plaid_txn.amount_cents),
            plaid_txn.posted_at,
        )
        return [
            {
                "plaid_transaction_id": plaid_txn.plaid_transaction_id,
                "external_id": plaid_txn.external_id,
                "amount_cents": plaid_txn.amount_cents,
                "posted_at": plaid_txn.posted_at,
                "merchant_descriptor": plaid_txn.merchant_descriptor,
                "category_id": None,
                "is_verified": False,
            }
        ]

    items = items_by_order.get(order.order_id, [])
    if not items:
        reconciler_logger.no_items_for_order(order.order_id)
        return [
            {
                "plaid_transaction_id": plaid_txn.plaid_transaction_id,
                "external_id": plaid_txn.external_id,
                "amount_cents": plaid_txn.amount_cents,
                "posted_at": plaid_txn.posted_at,
                "merchant_descriptor": plaid_txn.merchant_descriptor,
                "category_id": None,
                "is_verified": False,
            }
        ]

    item_subtotals = [item.price_cents * item.quantity for item in items]
    total_items_subtotal = sum(item_subtotals)
    overhead = order.tax_cents + order.shipping_cents

    derived_data: list[dict[str, Any]] = []
    allocated_total = 0

    for idx, (item, item_subtotal) in enumerate(zip(items, item_subtotals)):
        if idx == len(items) - 1:
            item_allocated = order.order_total_cents - allocated_total
        else:
            if total_items_subtotal > 0:
                item_proportion = item_subtotal / total_items_subtotal
                overhead_share = int(overhead * item_proportion)
            else:
                overhead_share = 0
            item_allocated = item_subtotal + overhead_share
            allocated_total += item_allocated

        derived_data.append(
            {
                "plaid_transaction_id": plaid_txn.plaid_transaction_id,
                "external_id": f"{plaid_txn.external_id}-{item.asin}",
                "amount_cents": item_allocated,
                "posted_at": plaid_txn.posted_at,
                "merchant_descriptor": f"Amazon: {item.description[:50]}",
                "category_id": None,
                "is_verified": False,
            }
        )

    return derived_data


def preserve_enrichments_by_amount(
    old_derived: list[DerivedTransaction],
    new_derived_data: list[dict[str, Any]],
    *,
    reconciler_logger: AmazonReconcilerLogger = _reconciler_logger,
) -> list[dict[str, Any]]:
    """Match old to new derived transactions by amount and preserve enrichments.

    Preserves category_id (if verified), is_verified, merchant_id.

    Args:
        old_derived: List of old DerivedTransaction instances
        new_derived_data: List of new derived transaction data dictionaries
        reconciler_logger: Logger instance for diagnostic output

    Returns:
        List of derived transaction data dictionaries with preserved enrichments
    """
    old_by_amount: dict[int, list[DerivedTransaction]] = {}
    for old_txn in old_derived:
        amount = old_txn.amount_cents
        if amount not in old_by_amount:
            old_by_amount[amount] = []
        old_by_amount[amount].append(old_txn)

    matched_old_ids: set[int] = set()
    for new_data in new_derived_data:
        amount = int(new_data["amount_cents"])

        if amount in old_by_amount:
            candidates = old_by_amount[amount]
            available = [
                c for c in candidates if c.transaction_id not in matched_old_ids
            ]

            if available:
                old_match = available[0]
                matched_old_ids.add(old_match.transaction_id)

                if old_match.is_verified and old_match.category_id is not None:
                    new_data["category_id"] = old_match.category_id
                new_data["is_verified"] = old_match.is_verified
                if old_match.merchant_id is not None:
                    new_data["merchant_id"] = old_match.merchant_id

                if len(available) > 1:
                    reconciler_logger.enrichment_multiple_matches(amount)
            else:
                reconciler_logger.enrichment_no_available_match(amount)
        else:
            reconciler_logger.enrichment_no_old_transaction(amount)

    unmatched_old = [
        txn for txn in old_derived if txn.transaction_id not in matched_old_ids
    ]
    if unmatched_old:
        amounts = [txn.amount_cents for txn in unmatched_old]
        reconciler_logger.enrichment_unmatched_old(len(unmatched_old), amounts)

    return new_derived_data
