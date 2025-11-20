from __future__ import annotations

from typing import List, Optional, TypedDict


class Transaction(TypedDict):
    """
    Transaction type mirroring Plaid's transaction structure.

    Note: This structure mirrors what Plaid's API returns and is subject to
    change as Plaid's API evolves. Fields match Plaid's transaction object.
    """
    transaction_id: Optional[str]
    account_id: str
    amount: float
    iso_currency_code: Optional[str]
    date: str
    name: str
    merchant_name: Optional[str]
    pending: bool
    payment_channel: Optional[str]
    unofficial_currency_code: Optional[str]
    category: Optional[List[str]]  # e.g., ["Food and Drink", "Groceries"]
    category_id: Optional[str]  # Unique category identifier

