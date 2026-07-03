"""Plaid wire-format types.

TypedDicts mirroring the shape of Plaid's API responses — the boundary
type between ``PlaidClient`` and downstream consumers (sync, categorizer).
Once ``PersistTool`` writes to the DB, everything reads the ORM models
instead; these types never leak past ingestion.
"""

from __future__ import annotations

from typing import Any, TypedDict


class PersonalFinanceCategory(TypedDict, total=False):
    """Personal finance category information from Plaid.

    Plaid's own category guess. Stored verbatim for analysis; NOT surfaced to
    the categorizer agent. ``total=False`` because Plaid populates these fields
    inconsistently across accounts.
    """

    version: str  # e.g., "v1"
    primary: str  # e.g., "FOOD_AND_DRINK"
    detailed: str  # e.g., "FOOD_AND_DRINK_RESTAURANT"
    confidence_level: str  # e.g., "MEDIUM"


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
    # Plaid's raw ``name`` — the fuller descriptor (e.g. "AplPay MY FAVORITE
    # CBROOKLYN"), before Plaid collapses it into ``merchant_name``.
    name: str
    merchant_name: str | None
    # Raw issuer description from Plaid (their field is ``original_description``;
    # we use the ``_descriptor`` suffix internally to match ``merchant_descriptor``).
    # Carries counterparty detail that ``name``/``merchant_name`` drop for wrapper
    # merchants — e.g. for a directly-linked Venmo item, "Jenny O'Leary :venmo_dollar:".
    original_descriptor: str | None
    pending: bool
    payment_channel: str | None
    unofficial_currency_code: str | None
    category: list[str] | None  # e.g., ["Food and Drink", "Groceries"]
    category_id: str | None  # Unique category identifier
    personal_finance_category: PersonalFinanceCategory | None
    # Plaid's structured counterparty list (merchant + payment counterparties).
    # Stored verbatim for analysis; NOT surfaced to the categorizer agent.
    counterparties: list[dict[str, Any]] | None
