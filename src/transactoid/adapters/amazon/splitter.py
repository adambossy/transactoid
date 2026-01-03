"""Item-level splitting with proportional tax/shipping allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from transactoid.adapters.amazon.csv_loader import AmazonItem, AmazonOrder
from transactoid.adapters.db.models import PlaidTransaction


@dataclass
class DerivedTransactionData:
    """Data for creating a derived transaction from an Amazon item."""

    plaid_transaction_id: int
    external_id: str
    amount_cents: int
    posted_at: date
    merchant_descriptor: str


def split_order_to_derived(
    plaid_txn: PlaidTransaction,
    order: AmazonOrder,
    items: list[AmazonItem],
) -> list[DerivedTransactionData]:
    """Split an Amazon order into item-level derived transactions.

    Allocates tax/shipping proportionally so item amounts sum exactly
    to the Plaid transaction amount.

    Args:
        plaid_txn: The Plaid transaction being split
        order: The matched Amazon order
        items: List of items in the order

    Returns:
        List of DerivedTransactionData, one per item.
        Returns single 1:1 transaction if items list is empty.
    """
    if not items:
        # No items - create 1:1 derived transaction
        return [
            DerivedTransactionData(
                plaid_transaction_id=plaid_txn.plaid_transaction_id,
                external_id=plaid_txn.external_id,
                amount_cents=plaid_txn.amount_cents,
                posted_at=plaid_txn.posted_at,
                merchant_descriptor=plaid_txn.merchant_descriptor or "Amazon",
            )
        ]

    # Calculate item subtotals (price * quantity)
    item_subtotals = [item.price_cents * item.quantity for item in items]
    total_subtotal = sum(item_subtotals)

    if total_subtotal == 0:
        # Edge case: all items are free - split evenly
        per_item = plaid_txn.amount_cents // len(items)
        remainder = plaid_txn.amount_cents % len(items)
        amounts = [per_item] * len(items)
        amounts[-1] += remainder
    else:
        # Proportional allocation
        amounts = _allocate_proportionally(
            plaid_txn.amount_cents, item_subtotals, total_subtotal
        )

    # Create derived transaction data for each item
    derived_list: list[DerivedTransactionData] = []

    for idx, (item, amount) in enumerate(zip(items, amounts, strict=True)):
        # Unique external_id: {plaid_external_id}:item:{idx}
        external_id = f"{plaid_txn.external_id}:item:{idx}"

        # Truncate description to reasonable length
        description = item.description[:50] if item.description else "Amazon item"

        derived_list.append(
            DerivedTransactionData(
                plaid_transaction_id=plaid_txn.plaid_transaction_id,
                external_id=external_id,
                amount_cents=amount,
                posted_at=plaid_txn.posted_at,
                merchant_descriptor=f"Amazon: {description}",
            )
        )

    return derived_list


def _allocate_proportionally(
    total_amount: int,
    subtotals: list[int],
    total_subtotal: int,
) -> list[int]:
    """Allocate total_amount proportionally based on subtotals.

    Uses largest remainder method to ensure amounts sum exactly to total_amount.

    Args:
        total_amount: Total amount to allocate (in cents)
        subtotals: Individual item subtotals
        total_subtotal: Sum of all subtotals

    Returns:
        List of allocated amounts that sum exactly to total_amount
    """
    n = len(subtotals)

    # Calculate proportional shares with remainders
    shares: list[float] = []
    for subtotal in subtotals:
        share = (subtotal / total_subtotal) * total_amount
        shares.append(share)

    # Floor each share
    floored = [int(share) for share in shares]
    remainders = [(shares[i] - floored[i], i) for i in range(n)]

    # Calculate how many cents we need to distribute
    distributed = sum(floored)
    to_distribute = total_amount - distributed

    # Distribute remaining cents to items with largest remainders
    remainders.sort(reverse=True)
    for i in range(to_distribute):
        idx = remainders[i][1]
        floored[idx] += 1

    return floored
