from __future__ import annotations

from datetime import date

from services.db import DB, CategoryRow
from services.taxonomy import Taxonomy
from tools.persist.persist_tool import ApplyTagsOutcome, PersistTool


def create_db() -> DB:
    """Create in-memory database instance."""
    db = DB("sqlite:///:memory:")
    # Create tables using SQLAlchemy Base
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
    ]
    db.replace_categories_rows(categories)
    return Taxonomy.from_db(db)


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
