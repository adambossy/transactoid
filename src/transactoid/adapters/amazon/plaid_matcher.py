"""Amazon order to Plaid transaction matching."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import re

from transactoid.adapters.amazon.csv_loader import AmazonItem, AmazonOrder
from transactoid.adapters.db.models import PlaidTransaction


class NoMatchReason(Enum):
    """Reasons why a Plaid transaction could not be matched to an Amazon order."""

    AMOUNT_NOT_FOUND = "amount_not_found"
    DATE_TOO_EARLY = "date_too_early"
    DATE_TOO_LATE = "date_too_late"
    ALREADY_MATCHED = "already_matched"


@dataclass
class MatchResult:
    """Result of matching a single Plaid transaction to an Amazon order."""

    plaid_transaction_id: int
    order_id: str | None
    items: list[AmazonItem] = field(default_factory=list)
    no_match_reason: NoMatchReason | None = None


@dataclass
class MatchingReport:
    """Aggregate report of all matching results."""

    total_amazon_transactions: int
    matched_count: int
    unmatched_count: int
    failure_reasons: dict[NoMatchReason, int]
    matched_results: list[MatchResult]
    unmatched_results: list[MatchResult]


# Amazon merchant detection patterns
_AMAZON_PATTERNS = [
    r"amazon",
    r"amzn",
    r"prime video",
    r"audible",
    r"kindle",
    r"whole foods",
]
_AMAZON_REGEX = re.compile("|".join(_AMAZON_PATTERNS), re.IGNORECASE)


def is_amazon_transaction(merchant_descriptor: str | None) -> bool:
    """Determine if a transaction is from Amazon based on merchant descriptor."""
    if not merchant_descriptor:
        return False
    return bool(_AMAZON_REGEX.search(merchant_descriptor))


def match_orders_to_transactions(
    amazon_orders: list[AmazonOrder],
    plaid_txns: list[PlaidTransaction],
    max_date_lag: int = 30,
) -> dict[str, int | None]:
    """Match Amazon orders to Plaid transactions.

    Uses O(N+M) algorithm with hash map lookup by amount.

    Args:
        amazon_orders: List of Amazon orders to match
        plaid_txns: List of Plaid transactions to match against
        max_date_lag: Maximum days between order_date and posted_at

    Returns:
        Dict mapping order_id -> matched plaid_transaction_id or None
    """
    # Build hash map: amount_cents -> list of transactions (O(M))
    txn_by_amount: dict[int, list[PlaidTransaction]] = defaultdict(list)
    for txn in plaid_txns:
        txn_by_amount[txn.amount_cents].append(txn)

    # Track which transactions have been matched
    used_txn_ids: set[int] = set()

    # Match each order (O(N) amortized)
    matches: dict[str, int | None] = {}

    for order in amazon_orders:
        candidates = txn_by_amount.get(order.order_total_cents, [])

        best_match: PlaidTransaction | None = None
        best_lag: int = max_date_lag + 1

        for txn in candidates:
            if txn.plaid_transaction_id in used_txn_ids:
                continue

            # Date lag: posted_at should be 0-N days AFTER order_date
            lag = (txn.posted_at - order.order_date).days

            if 0 <= lag <= max_date_lag and lag < best_lag:
                best_match = txn
                best_lag = lag

        if best_match:
            used_txn_ids.add(best_match.plaid_transaction_id)
            matches[order.order_id] = best_match.plaid_transaction_id
        else:
            matches[order.order_id] = None

    return matches
