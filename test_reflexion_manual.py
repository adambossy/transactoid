#!/usr/bin/env python3
"""Manual test for reflexion validator."""

from models.transaction import Transaction
from services.db import DB
from services.taxonomy import Taxonomy
from tools.categorize.categorizer_tool import Categorizer, CategorizedTransaction

# Create test transaction with invalid category
test_txn: Transaction = {
    "transaction_id": "test-123",
    "name": "HOME DEPOT - HOME DECOR",
    "merchant_name": "Home Depot",
    "amount": -45.99,
    "date": "2024-01-15",
    "account_id": "test-account",
    "iso_currency_code": "USD",
}

# Setup
db = DB("sqlite:///:memory:")
taxonomy = Taxonomy.from_db(db)

# Create a mock categorized transaction with invalid category
invalid_cat_txn = CategorizedTransaction(
    txn=test_txn,
    category_key="shopping_and_personal_care.home_decor",  # Invalid!
    category_confidence=0.85,
    category_rationale="Home improvement purchase at Home Depot",
)

print(f"Testing reflexion validator...")
print(f"Initial category: {invalid_cat_txn.category_key}")
print(f"Is valid: {taxonomy.is_valid_key(invalid_cat_txn.category_key)}")

# Test validation
categorizer = Categorizer(taxonomy)
invalid_indices = categorizer._find_invalid_category_indices([invalid_cat_txn])
print(f"Found {len(invalid_indices)} invalid categories")

if invalid_indices:
    print(f"✓ Successfully detected invalid category at index {invalid_indices[0]}")
    print("Reflexion validator logic is ready for integration testing")
else:
    print(f"✗ Failed to detect invalid category")

# Test what valid category should be
valid_key = "housing_and_utilities.home_decor"
print(f"\nCorrect category should be: {valid_key}")
print(f"Is valid: {taxonomy.is_valid_key(valid_key)}")
