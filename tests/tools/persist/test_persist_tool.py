from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session  # noqa: F401 - used in type comments

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import CategoryRow, normalize_merchant_name
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.persist.persist_tool import PersistTool


def create_db() -> DB:
    """Create in-memory database instance."""
    db = DB("sqlite:///:memory:")
    # Create tables using SQLAlchemy Base
    from transactoid.adapters.db.models import Base

    with db.session() as session:  # type: Session
        assert session.bind is not None
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
    ]
    db.replace_categories_rows(categories)
    return load_taxonomy_from_db(db)


def _get_merchant_id_for_descriptor(db: DB, descriptor: str) -> int:
    """Helper to resolve merchant_id created via merchant_descriptor."""
    # The DB layer normalizes merchant descriptors when inserting transactions,
    # so we use the same logic via the shared helper.
    normalized = normalize_merchant_name(descriptor)
    merchant = db.find_merchant_by_normalized_name(normalized)
    assert merchant is not None
    return merchant.merchant_id


def test_apply_tags_creates_tags_and_attaches_to_transactions() -> None:
    """Test apply_tags creates tags and attaches them to transactions."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

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

    outcome = persist_tool.apply_tags(
        [txn1.transaction_id, txn2.transaction_id], ["groceries", "essential"]
    )

    assert outcome.applied == 4  # 2 transactions × 2 tags
    assert set(outcome.created_tags) == {"groceries", "essential"}


def test_apply_tags_skips_duplicate_relationships() -> None:
    """Test apply_tags skips duplicate tag-transaction relationships."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

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

    outcome1 = persist_tool.apply_tags([txn.transaction_id], ["groceries"])
    outcome2 = persist_tool.apply_tags([txn.transaction_id], ["groceries"])

    assert outcome1.applied == 1
    assert outcome2.applied == 0  # Duplicate relationship skipped


def test_apply_tags_deduplicates_tag_names() -> None:
    """Test apply_tags deduplicates tag names in input."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

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

    outcome = persist_tool.apply_tags(
        [txn.transaction_id], ["groceries", "groceries", "essential"]
    )

    assert outcome.applied == 2  # Only 2 unique tags
    assert len(outcome.created_tags) == 2
    assert set(outcome.created_tags) == {"groceries", "essential"}


def test_apply_tags_returns_empty_for_empty_transaction_ids() -> None:
    """Test apply_tags returns empty outcome for empty transaction_ids."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

    outcome = persist_tool.apply_tags([], ["groceries"])

    assert outcome.applied == 0
    assert outcome.created_tags == []


def test_apply_tags_returns_empty_for_empty_tag_names() -> None:
    """Test apply_tags returns empty outcome for empty tag_names."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

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

    outcome = persist_tool.apply_tags([txn.transaction_id], [])

    assert outcome.applied == 0
    assert outcome.created_tags == []


def test_apply_tags_applies_multiple_tags_to_multiple_transactions() -> None:
    """Test apply_tags applies multiple tags to multiple transactions."""
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

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

    outcome = persist_tool.apply_tags(
        [txn1.transaction_id, txn2.transaction_id, txn3.transaction_id],
        ["groceries", "essential", "recurring"],
    )

    assert outcome.applied == 9  # 3 transactions × 3 tags
    assert set(outcome.created_tags) == {"groceries", "essential", "recurring"}


def test_bulk_recategorize_by_merchant_updates_unverified_transactions() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

    # Insert multiple unverified transactions for the same merchant
    descriptor = "My Coffee Shop 123"
    txn1 = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "merchant_descriptor": descriptor,
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
            "merchant_descriptor": descriptor,
        }
    )

    merchant_id = _get_merchant_id_for_descriptor(db, descriptor)
    category_id = db.get_category_id_by_key("food")
    assert category_id is not None
    assert txn1.category_id is None
    assert txn2.category_id is None

    updated_count = persist_tool.bulk_recategorize_by_merchant(
        merchant_id, "food", only_unverified=True
    )

    assert updated_count == 2

    # Verify both transactions now have the expected category_id
    refreshed_txns = db.fetch_transactions_by_ids_preserving_order(
        [txn1.transaction_id, txn2.transaction_id]
    )
    assert [t.category_id for t in refreshed_txns] == [category_id, category_id]


def test_bulk_recategorize_by_merchant_skips_verified_transactions() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

    descriptor = "Local Grocery 456"
    # Verified transaction should not be changed
    verified_txn = db.insert_transaction(
        {
            "external_id": "ext_v",
            "source": "PLAID",
            "account_id": "acc_v",
            "posted_at": date(2024, 1, 10),
            "amount_cents": 1500,
            "currency": "USD",
            "merchant_descriptor": descriptor,
            "is_verified": True,
        }
    )
    # Unverified transaction for the same merchant should be updated
    unverified_txn = db.insert_transaction(
        {
            "external_id": "ext_u",
            "source": "PLAID",
            "account_id": "acc_u",
            "posted_at": date(2024, 1, 11),
            "amount_cents": 2500,
            "currency": "USD",
            "merchant_descriptor": descriptor,
        }
    )

    merchant_id = _get_merchant_id_for_descriptor(db, descriptor)
    category_id = db.get_category_id_by_key("food")
    assert category_id is not None

    updated_count = persist_tool.bulk_recategorize_by_merchant(
        merchant_id, "food", only_unverified=True
    )

    assert updated_count == 1

    refreshed_verified, refreshed_unverified = (
        db.fetch_transactions_by_ids_preserving_order(
            [verified_txn.transaction_id, unverified_txn.transaction_id]
        )
    )
    # Verified should remain without category
    assert refreshed_verified.is_verified is True
    assert refreshed_verified.category_id is None
    # Unverified should be updated
    assert refreshed_unverified.is_verified is False
    assert refreshed_unverified.category_id == category_id


def test_bulk_recategorize_by_merchant_raises_for_invalid_category_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

    descriptor = "Unknown Merchant"
    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "merchant_descriptor": descriptor,
        }
    )
    merchant_id = _get_merchant_id_for_descriptor(db, descriptor)
    assert txn.category_id is None

    import pytest

    with pytest.raises(ValueError):
        persist_tool.bulk_recategorize_by_merchant(merchant_id, "invalid-key")


def test_bulk_recategorize_by_merchant_rejects_only_unverified_false() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    persist_tool = PersistTool(db, taxonomy)

    descriptor = "Another Shop"
    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "merchant_descriptor": descriptor,
        }
    )
    merchant_id = _get_merchant_id_for_descriptor(db, descriptor)
    assert txn.category_id is None

    import pytest

    with pytest.raises(ValueError):
        persist_tool.bulk_recategorize_by_merchant(
            merchant_id, "food", only_unverified=False
        )
