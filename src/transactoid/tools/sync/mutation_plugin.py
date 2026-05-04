"""Mutation plugin protocol for extensible transaction transformation.

Plugins can transform Plaid transactions into derived transactions with
custom logic (e.g., Amazon order splitting, Uber trip enrichment).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction

ItemizationSource = Literal["amazon_scrape", "email_receipt", "manual"]
SplitSource = Literal["user_split", "amazon_mutation", "email_mutation"]


@dataclass(frozen=True, slots=True)
class TransactionItemPayload:
    """Typed payload for a single line-item within a derived transaction.

    Attributes:
        description: Human-readable item description (truncated at source).
        amount_cents: Synthetic amount; all items for a transaction must sum
            exactly to the parent DerivedTransaction.amount_cents.
        quantity: Number of units (default 1).
        itemization_source: Origin of the item data.
        source_ref: Opaque upstream reference (e.g. Amazon order_id).
    """

    description: str
    amount_cents: int
    quantity: int = 1
    itemization_source: ItemizationSource = "amazon_scrape"
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedTransactionPayload:
    """Typed payload produced by a MutationPlugin for one derived transaction row.

    Required fields mirror those consumed by
    :meth:`~transactoid.adapters.db.facade.DB.bulk_insert_derived_transactions`.
    Optional fields carry enrichments preserved from existing derived rows or
    supplied by plugins.

    Attributes:
        plaid_transaction_id: FK to plaid_transactions.
        external_id: Stable dedup key (unique across derived_transactions).
        amount_cents: Amount in cents.
        posted_at: Settlement date from Plaid.
        merchant_descriptor: Raw merchant string from Plaid / Amazon.
        merchant_id: Resolved merchant FK (None if unresolved).
        category_id: Category FK (None if uncategorized).
        category_model: LLM model name used for categorization.
        category_method: How the category was assigned.
        category_assigned_at: When the category was assigned.
        category_reason: Audit reason for the category assignment.
        web_search_summary: LLM-generated merchant summary.
        is_verified: Whether this row is locked against mutation.
        reporting_mode: Investment reporting mode (None for regular txns).
        items: Line-item payloads (None = not itemized).
        split_source: How this row was split (None = not split).
        split_group_id: Shared UUID hex string for all rows in a multi-row split
            (None for 1:1 derived rows and non-split investment rows).
        split_index: Zero-based position within the split group (None when
            split_group_id is None).
    """

    plaid_transaction_id: int
    external_id: str
    amount_cents: int
    posted_at: date
    merchant_descriptor: str | None = None
    merchant_id: int | None = None
    category_id: int | None = None
    category_model: str | None = None
    category_method: str | None = None
    category_assigned_at: datetime | None = None
    category_reason: str | None = None
    web_search_summary: str | None = None
    is_verified: bool = False
    reporting_mode: str | None = None
    items: list[TransactionItemPayload] | None = field(default=None)
    split_source: SplitSource | None = None
    split_group_id: str | None = None
    split_index: int | None = None


@dataclass
class MutationResult:
    """Result of applying a mutation plugin to a transaction.

    Attributes:
        derived_data_list: Typed payloads for creating derived transactions.
            Length can be 1 (default 1:1) or N (splitting).
        handled: True if this plugin handled the transaction.
            When True, stops further plugin processing.
    """

    derived_data_list: list[DerivedTransactionPayload]
    handled: bool


@runtime_checkable
class MutationPlugin(Protocol):
    """Protocol for transaction mutation plugins.

    Plugins are applied in priority order during the MUTATE phase of sync.
    First plugin that returns handled=True wins.

    Attributes:
        name: Unique identifier for logging/debugging.
        priority: Lower numbers run first. Default fallback uses 100.
    """

    @property
    def name(self) -> str:
        """Unique plugin identifier."""
        ...

    @property
    def priority(self) -> int:
        """Plugin priority. Lower runs first."""
        ...

    def should_handle(self, plaid_txn: PlaidTransaction) -> bool:
        """Fast check if this plugin applies to the transaction.

        Called before process() to allow early filtering without
        expensive computation.

        Args:
            plaid_txn: The Plaid transaction to check.

        Returns:
            True if this plugin should process the transaction.
        """
        ...

    def process(
        self,
        plaid_txn: PlaidTransaction,
        old_derived: list[DerivedTransaction],
    ) -> MutationResult:
        """Process a transaction and return mutation result.

        Args:
            plaid_txn: The Plaid transaction to process.
            old_derived: Existing derived transactions for enrichment preservation.

        Returns:
            MutationResult with derived_data_list and handled flag.
        """
        ...
