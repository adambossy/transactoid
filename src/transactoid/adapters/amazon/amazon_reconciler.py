"""Amazon transaction reconciliation and splitting logic."""

from __future__ import annotations

import logging
from pathlib import Path

from transactoid.adapters.amazon.csv_loader import AmazonCSVLoader, CSVOrder
from transactoid.adapters.db.models import (
    DerivedTransaction,
    PlaidTransaction,
    normalize_merchant_name,
)

logger = logging.getLogger(__name__)


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


def find_matching_amazon_order(
    plaid_txn: PlaidTransaction,
    orders: dict[str, CSVOrder],
    date_tolerance_days: int = 3,
    amount_tolerance_cents: int = 50,
) -> CSVOrder | None:
    """Find Amazon order matching Plaid transaction.

    Match criteria:
    - Amount within tolerance
    - Date within tolerance
    - Return best match by date proximity

    Args:
        plaid_txn: Plaid transaction to match
        orders: Dictionary of Amazon orders (order_id → CSVOrder)
        date_tolerance_days: Maximum date difference in days (default: 3)
        amount_tolerance_cents: Maximum amount difference in cents (default: 50)

    Returns:
        Best matching CSVOrder or None if no match found
    """
    candidates: list[tuple[CSVOrder, int]] = []

    for order in orders.values():
        # Check amount (use absolute value for refunds)
        amount_diff = abs(abs(plaid_txn.amount_cents) - order.order_total_cents)
        if amount_diff > amount_tolerance_cents:
            continue

        # Check date
        date_diff = abs((plaid_txn.posted_at - order.order_date).days)
        if date_diff > date_tolerance_days:
            continue

        candidates.append((order, date_diff))

    if not candidates:
        return None

    # Return closest date match
    return min(candidates, key=lambda x: x[1])[0]


def create_split_derived_transactions(
    plaid_txn: PlaidTransaction,
    csv_dir: Path,
) -> list[dict]:
    """Create split derived transactions from Amazon order.

    Allocates tax and shipping proportionally based on item subtotals.

    Args:
        plaid_txn: Plaid transaction to split
        csv_dir: Directory containing Amazon CSV files

    Returns:
        List of derived transaction data dictionaries
    """
    # Load Amazon CSV data
    csv_loader = AmazonCSVLoader(csv_dir)
    orders, items_by_order = csv_loader.load_orders_and_items()

    # Find matching order
    order = find_matching_amazon_order(plaid_txn, orders)
    if not order:
        logger.warning(
            f"No Amazon order match for Plaid transaction {plaid_txn.external_id}"
        )
        # Return 1:1 derived transaction
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

    # Get items for order
    items = items_by_order.get(order.order_id, [])
    if not items:
        logger.error(f"No items found for Amazon order {order.order_id}")
        # Return 1:1 derived transaction
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

    # Calculate item subtotals and total
    item_subtotals = []
    for item in items:
        subtotal = item.price_cents * item.quantity  # Price per item * quantity
        item_subtotals.append(subtotal)

    total_items_subtotal = sum(item_subtotals)
    overhead = order.tax_cents + order.shipping_cents

    # Allocate proportionally with rounding adjustment
    derived_data: list[dict] = []
    allocated_total = 0

    for i, (item, item_subtotal) in enumerate(zip(items, item_subtotals)):
        # Last item gets rounding adjustment
        if i == len(items) - 1:
            item_allocated = order.order_total_cents - allocated_total
        else:
            # Proportional allocation
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
                "category_id": None,  # Will be categorized
                "is_verified": False,
            }
        )

    return derived_data


def preserve_enrichments_by_amount(
    old_derived: list[DerivedTransaction],
    new_derived_data: list[dict],
) -> list[dict]:
    """Match old to new derived transactions by amount and preserve enrichments.

    Preserves category_id (if verified), is_verified, merchant_id.

    Args:
        old_derived: List of old DerivedTransaction instances
        new_derived_data: List of new derived transaction data dictionaries

    Returns:
        List of derived transaction data dictionaries with preserved enrichments
    """
    # Index old transactions by amount
    old_by_amount: dict[int, list[DerivedTransaction]] = {}
    for old_txn in old_derived:
        amount = old_txn.amount_cents
        if amount not in old_by_amount:
            old_by_amount[amount] = []
        old_by_amount[amount].append(old_txn)

    # Match new to old and preserve
    matched_old_ids = set()
    for new_data in new_derived_data:
        amount = new_data["amount_cents"]

        if amount in old_by_amount:
            candidates = old_by_amount[amount]

            # Filter out already-matched
            available = [
                c for c in candidates if c.transaction_id not in matched_old_ids
            ]

            if available:
                old_match = available[0]
                matched_old_ids.add(old_match.transaction_id)

                # Preserve enrichments
                if old_match.is_verified and old_match.category_id is not None:
                    new_data["category_id"] = old_match.category_id
                new_data["is_verified"] = old_match.is_verified
                if old_match.merchant_id is not None:
                    new_data["merchant_id"] = old_match.merchant_id

                if len(available) > 1:
                    logger.warning(
                        f"Multiple old transactions with amount {amount}, matched first one"
                    )
            else:
                logger.info(
                    f"No available match for amount {amount} (all candidates already matched)"
                )
        else:
            logger.info(
                f"No old transaction found with amount {amount}, using fresh data"
            )

    # Warn about unmatched old transactions
    unmatched_old = [
        txn for txn in old_derived if txn.transaction_id not in matched_old_ids
    ]
    if unmatched_old:
        amounts = [txn.amount_cents for txn in unmatched_old]
        logger.warning(
            f"Unmatched old transactions: {len(unmatched_old)} with amounts {amounts}"
        )

    return new_derived_data
