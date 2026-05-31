"""Amazon adapters for scraped-order matching and Plaid mutation."""

from penny.adapters.amazon.entities import AmazonItem, AmazonOrder
from penny.adapters.amazon.logger import AmazonMatcherLogger
from penny.adapters.amazon.mutation_plugin import (
    AmazonMutationPlugin,
    AmazonMutationPluginConfig,
)
from penny.adapters.amazon.order_index import AmazonOrderIndex
from penny.adapters.amazon.plaid_matcher import (
    is_amazon_transaction,
    match_orders_to_transactions,
)
from penny.adapters.amazon.splitter import (
    DerivedTransactionData,
    split_order_to_derived,
)

__all__ = [
    # Entities
    "AmazonItem",
    "AmazonOrder",
    # Order index
    "AmazonOrderIndex",
    # Matching
    "is_amazon_transaction",
    "match_orders_to_transactions",
    # Splitting
    "DerivedTransactionData",
    "split_order_to_derived",
    # Mutation plugin
    "AmazonMutationPlugin",
    "AmazonMutationPluginConfig",
    # Logging
    "AmazonMatcherLogger",
]
