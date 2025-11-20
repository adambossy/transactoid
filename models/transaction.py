from __future__ import annotations

from typing import TypedDict


class PersonalFinanceCategory(TypedDict):
    """Personal finance category information from Plaid."""
    confidence_level: str  # e.g., "HIGH", "VERY_HIGH"
    detailed: str  # e.g., "GENERAL_SERVICES_OTHER_GENERAL_SERVICES"
    primary: str  # e.g., "GENERAL_SERVICES"
    version: str  # e.g., "v1"


class Transaction(TypedDict):
    """
    Transaction type mirroring Plaid's transaction structure.

    Note: This structure mirrors what Plaid's API returns and is subject to
    change as Plaid's API evolves. Fields match Plaid's transaction object.
    """
    transaction_id: str | None
    account_id: str
    amount: float
    iso_currency_code: str | None
    date: str
    name: str
    merchant_name: str | None
    pending: bool
    payment_channel: str | None
    unofficial_currency_code: str | None
    category: list[str] | None  # e.g., ["Food and Drink", "Groceries"]
    category_id: str | None  # Unique category identifier
    personal_finance_category: PersonalFinanceCategory | None

