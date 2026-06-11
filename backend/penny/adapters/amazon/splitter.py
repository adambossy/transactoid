"""Item-level splitting with proportional tax/shipping allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from penny.adapters.amazon.entities import AmazonItem, AmazonOrder
from penny.adapters.db.models import PlaidTransaction
from penny.tools._services.itemization import proportionally_allocate


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

    amounts = proportionally_allocate(
        total_cents=plaid_txn.amount_cents,
        item_amounts_cents=item_subtotals,
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
