"""Amazon adapters for CSV loading and Plaid transaction matching."""

from transactoid.adapters.amazon.csv_loader import (
    AmazonItemsCSVLoader,
    AmazonOrdersCSVLoader,
    CSVItem,
    CSVOrder,
)
from transactoid.adapters.amazon.logger import AmazonMatcherLogger
from transactoid.adapters.amazon.order_index import AmazonOrderIndex
from transactoid.adapters.amazon.plaid_matcher import (
    MatchingReport,
    MatchResult,
    NoMatchReason,
    is_amazon_transaction,
    match_orders_to_transactions,
)
from transactoid.adapters.amazon.splitter import (
    DerivedTransactionData,
    split_order_to_derived,
)

__all__ = [
    # CSV loading
    "AmazonItemsCSVLoader",
    "AmazonOrdersCSVLoader",
    "CSVItem",
    "CSVOrder",
    # Order index
    "AmazonOrderIndex",
    # Matching
    "MatchingReport",
    "MatchResult",
    "NoMatchReason",
    "is_amazon_transaction",
    "match_orders_to_transactions",
    # Splitting
    "DerivedTransactionData",
    "split_order_to_derived",
    # Logging
    "AmazonMatcherLogger",
]
