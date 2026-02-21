"""Tests for merchant rule matching and auto-verification behavior."""

from __future__ import annotations

from typing import Any, cast

import pytest

from models.transaction import Transaction
from transactoid.taxonomy.core import CategoryNode, Taxonomy
from transactoid.tools.categorize.categorizer_tool import (
    CategorizationResult,
    Categorizer,
)


@pytest.fixture(autouse=True)
def _set_openai_api_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def create_taxonomy() -> Taxonomy:
    """Create a sample taxonomy for testing."""
    nodes = [
        CategoryNode(key="food", name="Food", description=None, parent_key=None),
        CategoryNode(
            key="food.groceries",
            name="Groceries",
            description=None,
            parent_key="food",
        ),
        CategoryNode(
            key="transportation",
            name="Transportation",
            description=None,
            parent_key=None,
        ),
        CategoryNode(
            key="transportation.fuel",
            name="Fuel",
            description=None,
            parent_key="transportation",
        ),
    ]
    return Taxonomy.from_nodes(nodes)


def create_sample_transaction(*, idx: int = 0, name: str = "COSTCO GAS") -> Transaction:
    """Create a sample transaction for testing."""
    return cast(
        Transaction,
        {
            "transaction_id": f"txn_{idx}",
            "account_id": "acc_123",
            "amount": -35.00,
            "iso_currency_code": "USD",
            "date": "2024-01-15",
            "name": name,
            "merchant_name": "Costco",
            "pending": False,
            "payment_channel": "in store",
            "personal_finance_category": None,
            "idx": idx,
        },
    )


# --- Rule Matched Tests ---


def test_build_categorized_transaction_sets_verified_when_rule_matched() -> None:
    """When rule_matched=True, is_verified should be True."""
    taxonomy = create_taxonomy()
    categorizer = Categorizer(taxonomy)
    txn = create_sample_transaction()

    result = CategorizationResult(
        idx=0,
        category="transportation.fuel",
        score=0.95,
        rationale="Matched merchant rule",
        revised_category=None,
        revised_score=None,
        revised_rationale=None,
        merchant_summary=None,
        citations=None,
        rule_matched=True,
        rule_name="Costco Gas",
    )

    categorized = categorizer._build_categorized_transaction(result, [txn])

    assert categorized.rule_matched is True
    assert categorized.rule_name == "Costco Gas"
    assert categorized.is_verified is True


def test_build_categorized_transaction_not_verified_without_rule_match() -> None:
    """When rule_matched is not True, is_verified should be False."""
    taxonomy = create_taxonomy()
    categorizer = Categorizer(taxonomy)
    txn = create_sample_transaction()

    result = CategorizationResult(
        idx=0,
        category="transportation.fuel",
        score=0.75,
        rationale="General categorization",
        revised_category=None,
        revised_score=None,
        revised_rationale=None,
        merchant_summary=None,
        citations=None,
        rule_matched=None,
        rule_name=None,
    )

    categorized = categorizer._build_categorized_transaction(result, [txn])

    assert categorized.rule_matched is False
    assert categorized.rule_name is None
    assert categorized.is_verified is False


def test_build_categorized_transaction_not_verified_when_rule_matched_false() -> None:
    """When rule_matched=False explicitly, is_verified should be False."""
    taxonomy = create_taxonomy()
    categorizer = Categorizer(taxonomy)
    txn = create_sample_transaction()

    result = CategorizationResult(
        idx=0,
        category="food.groceries",
        score=0.80,
        rationale="Regular categorization",
        revised_category=None,
        revised_score=None,
        revised_rationale=None,
        merchant_summary=None,
        citations=None,
        rule_matched=False,
        rule_name=None,
    )

    categorized = categorizer._build_categorized_transaction(result, [txn])

    assert categorized.rule_matched is False
    assert categorized.rule_name is None
    assert categorized.is_verified is False
