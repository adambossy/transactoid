from __future__ import annotations

from datetime import date

import pytest

from models.transaction import Transaction
from services.db import (
    DB,
    CategoryRow,
    Merchant,
    Transaction as DBTransaction,
)
from services.taxonomy import Taxonomy
from tools.categorize.categorizer_tool import CategorizedTransaction


def create_db() -> DB:
    """Create in-memory database instance."""
    db = DB("sqlite:///:memory:")
    # Create tables
    from services.db import Base

    with db.session() as session:
        Base.metadata.create_all(session.bind)
    return db


def create_sample_taxonomy(db: DB) -> Taxonomy:
    """Create sample taxonomy in database and return Taxonomy instance."""
    categories: list[CategoryRow] = [
        CategoryRow(
            category_id=1,
            parent_id=None,
            key="food",
            name="Food",
            description="All food spend",
            parent_key=None,
        ),
        CategoryRow(
            category_id=2,
            parent_id=1,
            key="food.groceries",
            name="Groceries",
            description=None,
            parent_key="food",
        ),
        CategoryRow(
            category_id=3,
            parent_id=1,
            key="food.restaurants",
            name="Restaurants",
            description=None,
            parent_key="food",
        ),
        CategoryRow(
            category_id=4,
            parent_id=None,
            key="travel",
            name="Travel",
            description=None,
            parent_key=None,
        ),
    ]
    db.replace_categories_rows(categories)
    return Taxonomy.from_db(db)


def create_sample_transaction(
    *,
    transaction_id: str = "txn_123",
    account_id: str = "acc_456",
    amount: float = 50.00,
    date_str: str = "2024-01-15",
    name: str = "Whole Foods",
    merchant_name: str | None = None,
) -> Transaction:
    """Create sample Transaction TypedDict."""
    return Transaction(
        transaction_id=transaction_id,
        account_id=account_id,
        amount=amount,
        iso_currency_code="USD",
        date=date_str,
        name=name,
        merchant_name=merchant_name,
        pending=False,
        payment_channel=None,
        unofficial_currency_code=None,
        category=None,
        category_id=None,
        personal_finance_category=None,
    )


def create_categorized_transaction(
    txn: Transaction,
    *,
    category_key: str = "food.groceries",
    revised_category_key: str | None = None,
) -> CategorizedTransaction:
    """Create CategorizedTransaction from Transaction."""
    return CategorizedTransaction(
        txn=txn,
        category_key=category_key,
        category_confidence=0.85,
        category_rationale="Test rationale",
        revised_category_key=revised_category_key,
    )


def test_db_session_context_manager() -> None:
    """Test session context manager commits and rolls back correctly."""
    db = create_db()

    with db.session() as session:
        merchant = Merchant(normalized_name="test_merchant", display_name="Test")
        session.add(merchant)
        session.flush()
        merchant_id = merchant.merchant_id

    # Verify commit worked
    found = db.find_merchant_by_normalized_name("test_merchant")
    assert found is not None
    assert found.merchant_id == merchant_id


def test_fetch_categories_returns_all_categories() -> None:
    """Test fetch_categories returns all categories as CategoryRow."""
    db = create_db()
    create_sample_taxonomy(db)

    categories = db.fetch_categories()

    assert len(categories) == 4
    assert {cat["key"] for cat in categories} == {
        "food",
        "food.groceries",
        "food.restaurants",
        "travel",
    }
    groceries = next(cat for cat in categories if cat["key"] == "food.groceries")
    assert groceries["parent_id"] is not None
    assert groceries["parent_key"] == "food"


def test_replace_categories_rows_replaces_all_categories() -> None:
    """Test replace_categories_rows deletes old and inserts new categories."""
    db = create_db()
    create_sample_taxonomy(db)

    new_categories: list[CategoryRow] = [
        CategoryRow(
            category_id=10,
            parent_id=None,
            key="shopping",
            name="Shopping",
            description=None,
            parent_key=None,
        ),
    ]
    db.replace_categories_rows(new_categories)

    categories = db.fetch_categories()
    assert len(categories) == 1
    assert categories[0]["key"] == "shopping"


def test_get_category_id_by_key_returns_id() -> None:
    """Test get_category_id_by_key returns category ID for valid key."""
    db = create_db()
    create_sample_taxonomy(db)

    groceries_id = db.get_category_id_by_key("food.groceries")
    missing_id = db.get_category_id_by_key("unknown.key")

    assert groceries_id == 2
    assert missing_id is None


def test_find_merchant_by_normalized_name() -> None:
    """Test find_merchant_by_normalized_name finds existing merchant."""
    db = create_db()

    db.create_merchant(normalized_name="whole foods", display_name="Whole Foods")

    found = db.find_merchant_by_normalized_name("whole foods")
    not_found = db.find_merchant_by_normalized_name("unknown merchant")

    assert found is not None
    assert found.normalized_name == "whole foods"
    assert found.display_name == "Whole Foods"
    assert not_found is None


def test_create_merchant_creates_new_merchant() -> None:
    """Test create_merchant inserts new merchant."""
    db = create_db()

    merchant = db.create_merchant(
        normalized_name="test_merchant", display_name="Test Merchant"
    )

    assert merchant.merchant_id is not None
    assert merchant.normalized_name == "test_merchant"
    assert merchant.display_name == "Test Merchant"


def test_get_transaction_by_external_finds_transaction() -> None:
    """Test get_transaction_by_external finds transaction by external_id and source."""
    db = create_db()
    create_sample_taxonomy(db)

    txn_data = {
        "external_id": "ext_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
        "merchant_descriptor": "Whole Foods",
    }
    inserted = db.insert_transaction(txn_data)

    found = db.get_transaction_by_external(external_id="ext_123", source="PLAID")
    not_found = db.get_transaction_by_external(external_id="ext_999", source="PLAID")

    assert found is not None
    assert found.transaction_id == inserted.transaction_id
    assert not_found is None


def test_insert_transaction_creates_transaction_with_merchant() -> None:
    """Test insert_transaction creates transaction and resolves merchant."""
    db = create_db()
    create_sample_taxonomy(db)

    txn_data = {
        "external_id": "ext_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
        "merchant_descriptor": "Whole Foods Market",
    }
    transaction = db.insert_transaction(txn_data)

    assert transaction.transaction_id is not None
    assert transaction.external_id == "ext_123"
    assert transaction.merchant_descriptor == "Whole Foods Market"
    assert transaction.merchant_id is not None

    # Verify merchant was created
    merchant = db.find_merchant_by_normalized_name("whole foods market")
    assert merchant is not None


def test_update_transaction_mutable_updates_unverified_transaction() -> None:
    """Test update_transaction_mutable updates unverified transaction."""
    db = create_db()
    create_sample_taxonomy(db)

    txn_data = {
        "external_id": "ext_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
    }
    transaction = db.insert_transaction(txn_data)
    category_id = db.get_category_id_by_key("food.groceries")

    updated = db.update_transaction_mutable(
        transaction.transaction_id, {"category_id": category_id, "amount_cents": 6000}
    )

    assert updated.category_id == category_id
    assert updated.amount_cents == 6000


def test_update_transaction_mutable_raises_for_verified_transaction() -> None:
    """Test update_transaction_mutable raises error for verified transaction."""
    db = create_db()
    create_sample_taxonomy(db)

    txn_data = {
        "external_id": "ext_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
        "is_verified": True,
    }
    transaction = db.insert_transaction(txn_data)

    with pytest.raises(ValueError, match="verified and cannot be updated"):
        db.update_transaction_mutable(transaction.transaction_id, {"category_id": 1})


def test_fetch_transactions_by_ids_preserves_order() -> None:
    """Test fetch_transactions_by_ids_preserving_order returns in input order."""
    db = create_db()
    create_sample_taxonomy(db)

    txn1 = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
        }
    )
    txn2 = db.insert_transaction(
        {
            "external_id": "ext_2",
            "source": "PLAID",
            "account_id": "acc_2",
            "posted_at": date(2024, 1, 16),
            "amount_cents": 2000,
            "currency": "USD",
        }
    )
    txn3 = db.insert_transaction(
        {
            "external_id": "ext_3",
            "source": "PLAID",
            "account_id": "acc_3",
            "posted_at": date(2024, 1, 17),
            "amount_cents": 3000,
            "currency": "USD",
        }
    )

    # Request in reverse order
    fetched = db.fetch_transactions_by_ids_preserving_order(
        [txn3.transaction_id, txn1.transaction_id, txn2.transaction_id]
    )

    assert len(fetched) == 3
    assert fetched[0].transaction_id == txn3.transaction_id
    assert fetched[1].transaction_id == txn1.transaction_id
    assert fetched[2].transaction_id == txn2.transaction_id


def test_save_transactions_inserts_new_transaction() -> None:
    """Test save_transactions inserts new transaction."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)

    txn = create_sample_transaction(transaction_id="plaid_txn_123")
    cat_txn = create_categorized_transaction(txn, category_key="food.groceries")

    outcome = db.save_transactions(taxonomy, [cat_txn])

    assert outcome.inserted == 1
    assert outcome.updated == 0
    assert outcome.skipped_verified == 0
    assert outcome.skipped_duplicate == 0
    assert len(outcome.rows) == 1
    assert outcome.rows[0].action == "inserted"
    assert outcome.rows[0].transaction_id is not None


def test_save_transactions_skips_verified_transaction() -> None:
    """Test save_transactions skips verified transaction (Plaid Added + DB Verified)."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)

    # Insert verified transaction first
    txn_data = {
        "external_id": "plaid_txn_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
        "is_verified": True,
    }
    existing = db.insert_transaction(txn_data)

    # Try to save same transaction
    txn = create_sample_transaction(transaction_id="plaid_txn_123")
    cat_txn = create_categorized_transaction(txn, category_key="food.groceries")

    outcome = db.save_transactions(taxonomy, [cat_txn])

    assert outcome.inserted == 0
    assert outcome.updated == 0
    assert outcome.skipped_verified == 1
    assert outcome.rows[0].action == "skipped-verified"
    assert outcome.rows[0].transaction_id == existing.transaction_id


def test_save_transactions_updates_unverified_transaction() -> None:
    """Test save_transactions updates unverified transaction."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)

    # Insert unverified transaction first
    txn_data = {
        "external_id": "plaid_txn_123",
        "source": "PLAID",
        "account_id": "acc_456",
        "posted_at": date(2024, 1, 15),
        "amount_cents": 5000,
        "currency": "USD",
        "is_verified": False,
    }
    existing = db.insert_transaction(txn_data)

    # Update with new category
    txn = create_sample_transaction(transaction_id="plaid_txn_123", amount=60.00)
    cat_txn = create_categorized_transaction(txn, category_key="food.restaurants")

    outcome = db.save_transactions(taxonomy, [cat_txn])

    assert outcome.inserted == 0
    assert outcome.updated == 1
    assert outcome.skipped_verified == 0
    assert outcome.rows[0].action == "updated"
    assert outcome.rows[0].transaction_id == existing.transaction_id

    # Verify update
    updated = db.get_transaction_by_external(
        external_id="plaid_txn_123", source="PLAID"
    )
    assert updated is not None
    assert updated.amount_cents == 6000
    assert updated.category_id == db.get_category_id_by_key("food.restaurants")


def test_save_transactions_prefers_revised_category_key() -> None:
    """Test save_transactions prefers revised_category_key over category_key."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)

    txn = create_sample_transaction(transaction_id="plaid_txn_123")
    cat_txn = create_categorized_transaction(
        txn,
        category_key="food.groceries",
        revised_category_key="food.restaurants",
    )

    outcome = db.save_transactions(taxonomy, [cat_txn])

    assert outcome.inserted == 1
    inserted_txn = db.get_transaction_by_external(
        external_id="plaid_txn_123", source="PLAID"
    )
    assert inserted_txn is not None
    assert inserted_txn.category_id == db.get_category_id_by_key("food.restaurants")


def test_save_transactions_merchant_normalization_deduplication() -> None:
    """Test save_transactions normalizes merchant names and deduplicates merchants."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)

    txn1 = create_sample_transaction(
        transaction_id="txn_1", merchant_name="Whole Foods Market 123"
    )
    txn2 = create_sample_transaction(
        transaction_id="txn_2", merchant_name="WHOLE FOODS MARKET"
    )
    cat_txn1 = create_categorized_transaction(txn1)
    cat_txn2 = create_categorized_transaction(txn2)

    outcome = db.save_transactions(taxonomy, [cat_txn1, cat_txn2])

    assert outcome.inserted == 2

    # Verify both transactions share same merchant
    txn1_db = db.get_transaction_by_external(external_id="txn_1", source="PLAID")
    txn2_db = db.get_transaction_by_external(external_id="txn_2", source="PLAID")

    assert txn1_db is not None
    assert txn2_db is not None
    assert txn1_db.merchant_id == txn2_db.merchant_id


def test_upsert_tag_creates_new_tag() -> None:
    """Test upsert_tag creates new tag."""
    db = create_db()

    tag = db.upsert_tag("groceries", "Grocery shopping")

    assert tag.tag_id is not None
    assert tag.name == "groceries"
    assert tag.description == "Grocery shopping"


def test_upsert_tag_updates_existing_tag() -> None:
    """Test upsert_tag updates existing tag."""
    db = create_db()

    tag1 = db.upsert_tag("groceries", "Original description")
    tag2 = db.upsert_tag("groceries", "Updated description")

    assert tag1.tag_id == tag2.tag_id
    assert tag2.description == "Updated description"


def test_attach_tags_creates_relationships() -> None:
    """Test attach_tags creates transaction-tag relationships."""
    db = create_db()
    create_sample_taxonomy(db)

    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
        }
    )
    tag1 = db.upsert_tag("groceries")
    tag2 = db.upsert_tag("essential")

    count = db.attach_tags([txn.transaction_id], [tag1.tag_id, tag2.tag_id])

    assert count == 2


def test_attach_tags_skips_duplicates() -> None:
    """Test attach_tags skips existing relationships."""
    db = create_db()
    create_sample_taxonomy(db)

    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
        }
    )
    tag = db.upsert_tag("groceries")

    count1 = db.attach_tags([txn.transaction_id], [tag.tag_id])
    count2 = db.attach_tags([txn.transaction_id], [tag.tag_id])

    assert count1 == 1
    assert count2 == 0


def test_recategorize_unverified_by_merchant() -> None:
    """Test recategorize_unverified_by_merchant updates unverified transactions."""
    db = create_db()
    create_sample_taxonomy(db)

    merchant = db.create_merchant(normalized_name="test_merchant", display_name="Test")

    _ = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "merchant_id": merchant.merchant_id,
            "is_verified": False,
        }
    )
    _ = db.insert_transaction(
        {
            "external_id": "ext_2",
            "source": "PLAID",
            "account_id": "acc_2",
            "posted_at": date(2024, 1, 16),
            "amount_cents": 2000,
            "currency": "USD",
            "merchant_id": merchant.merchant_id,
            "is_verified": True,  # Verified, should not be updated
        }
    )

    groceries_id = db.get_category_id_by_key("food.groceries")
    count = db.recategorize_unverified_by_merchant(merchant.merchant_id, groceries_id)

    assert count == 1

    updated_txn1 = db.get_transaction_by_external(external_id="ext_1", source="PLAID")
    updated_txn2 = db.get_transaction_by_external(external_id="ext_2", source="PLAID")

    assert updated_txn1 is not None
    assert updated_txn1.category_id == groceries_id
    assert updated_txn2 is not None
    assert updated_txn2.category_id is None  # Verified transaction not updated


def test_delete_transactions_by_external_ids_deletes_unverified_only() -> None:
    """Test delete_transactions_by_external_ids only deletes unverified transactions."""
    db = create_db()
    create_sample_taxonomy(db)

    _ = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "is_verified": False,
        }
    )
    _ = db.insert_transaction(
        {
            "external_id": "ext_2",
            "source": "PLAID",
            "account_id": "acc_2",
            "posted_at": date(2024, 1, 16),
            "amount_cents": 2000,
            "currency": "USD",
            "is_verified": True,  # Verified, should not be deleted
        }
    )

    count = db.delete_transactions_by_external_ids(["ext_1", "ext_2"], source="PLAID")

    assert count == 1

    deleted_txn1 = db.get_transaction_by_external(external_id="ext_1", source="PLAID")
    remaining_txn2 = db.get_transaction_by_external(external_id="ext_2", source="PLAID")

    assert deleted_txn1 is None
    assert remaining_txn2 is not None


def test_compact_schema_hint_returns_schema_metadata() -> None:
    """Test compact_schema_hint returns schema metadata for LLM prompts."""
    db = create_db()

    hint = db.compact_schema_hint()

    assert "tables" in hint
    assert "merchants" in hint["tables"]
    assert "categories" in hint["tables"]
    assert "transactions" in hint["tables"]
    assert "tags" in hint["tables"]
    assert "transaction_tags" in hint["tables"]

    transactions_table = hint["tables"]["transactions"]
    assert "columns" in transactions_table
    assert "relationships" in transactions_table
    assert "transaction_id" in transactions_table["columns"]


def test_run_sql_executes_raw_sql_and_returns_orm_models() -> None:
    """Test run_sql executes raw SQL and returns ORM models in order."""
    db = create_db()
    create_sample_taxonomy(db)

    txn1 = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
        }
    )
    txn2 = db.insert_transaction(
        {
            "external_id": "ext_2",
            "source": "PLAID",
            "account_id": "acc_2",
            "posted_at": date(2024, 1, 16),
            "amount_cents": 2000,
            "currency": "USD",
        }
    )

    # Use f-string for SQL (acceptable in tests with controlled integer values)
    sql = (  # noqa: S608
        f"""
    SELECT transaction_id, external_id, amount_cents
    FROM transactions
    WHERE transaction_id IN ({txn1.transaction_id}, {txn2.transaction_id})
    ORDER BY amount_cents DESC
    """
    )

    results = db.run_sql(sql, model=DBTransaction, pk_column="transaction_id")

    assert len(results) == 2
    # Should be in SQL order (DESC by amount_cents)
    assert results[0].transaction_id == txn2.transaction_id
    assert results[1].transaction_id == txn1.transaction_id
