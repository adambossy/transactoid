from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
from transactoid.tools.sync.mutation_registry import MutationRegistry


@dataclass
class PlaidTxnInput:
    plaid_transaction_id: int
    external_id: str
    amount_cents: int
    posted_at: date
    merchant_descriptor: str


@dataclass
class OldDerivedInput:
    category_id: int | None
    is_verified: bool
    merchant_id: int | None
    category_model: str | None
    category_method: str | None
    category_assigned_at: datetime | None
    web_search_summary: str | None


def test_mutation_registry_default_mutation_preserves_llm_summary() -> None:
    # input
    plaid_transaction_id = 1
    external_id = "txn_123"
    amount_cents = 1500
    posted_at = date(2024, 1, 15)
    merchant_descriptor = "Cafe ABC"
    llm_summary = "- Local coffee shop in Austin"

    # helper setup
    registry = MutationRegistry()
    plaid_txn = PlaidTxnInput(
        plaid_transaction_id=plaid_transaction_id,
        external_id=external_id,
        amount_cents=amount_cents,
        posted_at=posted_at,
        merchant_descriptor=merchant_descriptor,
    )
    old_derived = [
        OldDerivedInput(
            category_id=3,
            is_verified=True,
            merchant_id=5,
            category_model="gpt-5.2",
            category_method="llm",
            category_assigned_at=datetime(2026, 2, 9, 12, 0, 0),
            web_search_summary=llm_summary,
        )
    ]
    plaid_txn_typed = cast(PlaidTransaction, plaid_txn)
    old_derived_typed = cast(list[DerivedTransaction], old_derived)

    # act
    output = registry.process(plaid_txn_typed, old_derived_typed)

    # expected
    expected_output = llm_summary

    # assert
    assert output.derived_data_list[0]["web_search_summary"] == expected_output
