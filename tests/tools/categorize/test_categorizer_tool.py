"""Tests for categorizer tool merchant summary functionality."""

from typing import cast

from models.transaction import Transaction
from transactoid.tools.categorize.categorizer_tool import (
    CategorizationResult,
    CategorizedTransaction,
)


def test_categorization_result_parses_with_merchant_summary() -> None:
    """Test CategorizationResult parses JSON with merchant_summary field."""
    # Input
    json_data = {
        "idx": 0,
        "category": "food_and_dining.restaurants",
        "score": 0.65,
        "rationale": "Low confidence",
        "revised_category": "food_and_dining.restaurants",
        "revised_score": 0.85,
        "revised_rationale": "Found via search",
        "merchant_summary": (
            "- Small local cafe\n- Serves breakfast and lunch\n- Located in downtown"
        ),
        "citations": ["https://example.com"],
    }

    # Act
    result = CategorizationResult.model_validate(json_data)

    # Assert
    assert (
        result.merchant_summary
        == "- Small local cafe\n- Serves breakfast and lunch\n- Located in downtown"
    )


def test_categorization_result_parses_without_merchant_summary() -> None:
    """Test backward compatibility: JSON without merchant_summary parses correctly."""
    # Input (old format)
    json_data = {
        "idx": 0,
        "category": "food_and_dining.groceries",
        "score": 0.85,
        "rationale": "High confidence",
        "revised_category": None,
        "revised_score": None,
        "revised_rationale": None,
        "citations": None,
    }

    # Act
    result = CategorizationResult.model_validate(json_data)

    # Assert
    assert result.merchant_summary is None


def test_categorized_transaction_includes_merchant_summary() -> None:
    """Test CategorizedTransaction includes merchant_summary field."""
    # Setup
    txn = cast(
        Transaction,
        {
            "transaction_id": "txn_123",
            "account_id": "acc_123",
            "amount": -12.50,
            "iso_currency_code": "USD",
            "date": "2024-01-15",
            "name": "ACME CAFE",
            "merchant_name": "Acme Cafe",
            "pending": False,
            "payment_channel": "in store",
            "personal_finance_category": None,
            "idx": 0,
        },
    )

    # Act
    categorized = CategorizedTransaction(
        txn=txn,
        category_key="food_and_dining.restaurants",
        category_confidence=0.85,
        category_rationale="Web search confirmed",
        revised_category_key="food_and_dining.restaurants",
        revised_category_confidence=0.85,
        revised_category_rationale="Search confirmed",
        merchant_summary="- Local diner\n- Family owned\n- American cuisine",
    )

    # Assert
    assert (
        categorized.merchant_summary
        == "- Local diner\n- Family owned\n- American cuisine"
    )
