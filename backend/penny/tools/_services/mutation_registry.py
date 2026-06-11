"""Registry for mutation plugins with default fallback behavior.

The registry applies plugins in priority order and falls back to 1:1
transaction mapping if no plugin handles a transaction.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from penny.tools._services.mutation_plugin import (
    DerivedTransactionPayload,
    MutationPlugin,
    MutationResult,
)

if TYPE_CHECKING:
    from penny.adapters.db.models import DerivedTransaction, PlaidTransaction


class MutationRegistry:
    """Registry of mutation plugins applied during sync MUTATE phase.

    Plugins are tried in priority order (lower first). First plugin that
    returns handled=True wins. If no plugin handles, default 1:1 mapping
    is applied.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._plugins: list[MutationPlugin] = []

    def register(self, plugin: MutationPlugin) -> None:
        """Register a plugin and re-sort by priority.

        Args:
            plugin: Plugin to register.
        """
        self._plugins.append(plugin)
        self._plugins.sort(key=lambda p: p.priority)

    def initialize_plugins(self, plaid_txns: list[PlaidTransaction]) -> None:
        """Initialize plugins that need batch context.

        Called once per batch before processing individual transactions.
        Plugins that implement `initialize()` can pre-compute matches
        for O(N+M) efficiency.

        Args:
            plaid_txns: All Plaid transactions in the current batch.
        """
        for plugin in self._plugins:
            if hasattr(plugin, "initialize"):
                plugin.initialize(plaid_txns)

    def process(
        self,
        plaid_txn: PlaidTransaction,
        old_derived: list[DerivedTransaction],
    ) -> MutationResult:
        """Process transaction through registered plugins.

        Plugins are tried in priority order. First plugin that returns
        handled=True wins. If no plugin handles, returns default 1:1 result.

        Args:
            plaid_txn: The Plaid transaction to process.
            old_derived: Existing derived transactions for enrichment preservation.

        Returns:
            MutationResult with derived transaction data.
        """
        for plugin in self._plugins:
            if plugin.should_handle(plaid_txn):
                result = plugin.process(plaid_txn, old_derived)
                if result.handled:
                    return result

        # Default fallback: 1:1 mapping
        return self._default_mutation(plaid_txn, old_derived)

    def _default_mutation(
        self,
        plaid_txn: PlaidTransaction,
        old_derived: list[DerivedTransaction],
    ) -> MutationResult:
        """Default 1:1 derived transaction with enrichment preservation.

        Creates a single derived transaction that mirrors the Plaid transaction,
        preserving category, merchant, and verification status from existing
        derived transactions when applicable.

        Args:
            plaid_txn: The Plaid transaction to transform.
            old_derived: Existing derived transactions for enrichment preservation.

        Returns:
            MutationResult with single derived transaction data.
        """
        new_payload = DerivedTransactionPayload(
            plaid_transaction_id=plaid_txn.plaid_transaction_id,
            external_id=plaid_txn.external_id,
            amount_cents=plaid_txn.amount_cents,
            posted_at=plaid_txn.posted_at,
            merchant_descriptor=plaid_txn.merchant_descriptor,
        )

        # Preserve enrichments from old derived if exists (1:1 only)
        if old_derived and len(old_derived) == 1:
            old = old_derived[0]
            preserve_category = old.is_verified and old.category_id is not None
            new_payload = dataclasses.replace(
                new_payload,
                merchant_id=old.merchant_id,
                category_id=old.category_id if preserve_category else None,
                category_model=old.category_model if preserve_category else None,
                category_method=old.category_method if preserve_category else None,
                category_assigned_at=(
                    old.category_assigned_at if preserve_category else None
                ),
                web_search_summary=old.web_search_summary,
                is_verified=old.is_verified,
            )

        return MutationResult(
            derived_data_list=[new_payload],
            handled=True,
        )
