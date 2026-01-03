"""Mutation plugin protocol for extensible transaction transformation.

Plugins can transform Plaid transactions into derived transactions with
custom logic (e.g., Amazon order splitting, Uber trip enrichment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction


@dataclass
class MutationResult:
    """Result of applying a mutation plugin to a transaction.

    Attributes:
        derived_data_list: List of dicts for creating derived transactions.
            Each dict contains fields for DerivedTransaction creation.
            Length can be 1 (default 1:1) or N (splitting).
        handled: True if this plugin handled the transaction.
            When True, stops further plugin processing.
    """

    derived_data_list: list[dict[str, Any]]
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
