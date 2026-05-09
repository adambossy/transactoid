from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import CategoryRow
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.migrate.migration_tool import MigrationTool

if TYPE_CHECKING:
    from transactoid.tools.categorize.categorizer_tool import Categorizer


def create_db() -> DB:
    """Create in-memory database instance."""
    db = DB("sqlite:///:memory:")
    from transactoid.adapters.db.models import Base

    with db.session() as session:
        assert session.bind is not None
        Base.metadata.create_all(session.bind)
    return db


def create_sample_taxonomy(db: DB) -> Taxonomy:
    """Create sample taxonomy with parent and child categories."""
    categories: list[CategoryRow] = [
        CategoryRow(
            category_id=1,
            parent_id=None,
            key="food",
            name="Food",
            description="All food spend",
            parent_key=None,
            deprecated_at=None,
        ),
        CategoryRow(
            category_id=2,
            parent_id=1,
            key="food.groceries",
            name="Groceries",
            description=None,
            parent_key="food",
            deprecated_at=None,
        ),
        CategoryRow(
            category_id=3,
            parent_id=1,
            key="food.restaurants",
            name="Restaurants",
            description="Dining out",
            parent_key="food",
            deprecated_at=None,
        ),
        CategoryRow(
            category_id=4,
            parent_id=None,
            key="travel",
            name="Travel",
            description="Travel expenses",
            parent_key=None,
            deprecated_at=None,
        ),
    ]
    db.replace_categories_rows(categories)
    return load_taxonomy_from_db(db)


def create_mock_categorizer() -> Categorizer:
    """Create a mock categorizer for testing."""
    mock = MagicMock()
    mock.categorize = AsyncMock(return_value=[])
    mock.categorize_constrained = AsyncMock(return_value=[])
    return cast("Categorizer", mock)


# --- Add Category Tests ---


def test_add_category_creates_new_root_category() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.add_category("health", "Health", None, "Healthcare spending")

    assert result.success is True
    assert result.operation == "add"
    assert tool.taxonomy.is_valid_key("health")
    node = tool.taxonomy.get("health")
    assert node is not None
    assert node.name == "Health"
    assert node.description == "Healthcare spending"


def test_add_category_creates_child_category() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.add_category("food.delivery", "Delivery", "food", "Food delivery")

    assert result.success is True
    assert tool.taxonomy.is_valid_key("food.delivery")
    node = tool.taxonomy.get("food.delivery")
    assert node is not None
    assert node.parent_key == "food"


def test_add_category_syncs_to_database() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    tool.add_category("health", "Health", None)

    category_id = db.get_category_id_by_key("health")
    assert category_id is not None


def test_add_category_fails_for_duplicate_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.add_category("food", "Duplicate", None)

    assert result.success is False
    assert "already exists" in result.errors[0]


def test_add_category_fails_for_nonexistent_parent() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.add_category("nonexistent.child", "Child", "nonexistent")

    assert result.success is False
    assert "does not exist" in result.errors[0]


# --- Remove Category Tests ---


def test_remove_category_removes_leaf_category() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.remove_category("food.restaurants")

    assert result.success is True
    assert result.operation == "remove"
    assert not tool.taxonomy.is_valid_key("food.restaurants")
    assert tool.taxonomy.is_valid_key("food")


def test_remove_category_with_transactions_requires_fallback() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    category_id = db.get_category_id_by_key("food.groceries")
    assert category_id is not None
    db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "category_id": category_id,
        }
    )

    result = tool.remove_category("food.groceries")

    assert result.success is False
    assert "has 1 transactions" in result.errors[0]


def test_remove_category_with_transactions_and_fallback() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    category_id = db.get_category_id_by_key("food.groceries")
    assert category_id is not None
    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "category_id": category_id,
        }
    )

    result = tool.remove_category("food.groceries", fallback_key="food.restaurants")

    assert result.success is True
    assert result.affected_transaction_count == 1

    refreshed = db.fetch_transactions_by_ids_preserving_order([txn.transaction_id])
    restaurants_id = db.get_category_id_by_key("food.restaurants")
    assert refreshed[0].category_id == restaurants_id


def test_remove_category_fails_for_nonexistent_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.remove_category("nonexistent")

    assert result.success is False


def test_remove_category_fails_for_category_with_children() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.remove_category("food")

    assert result.success is False
    assert "has children" in result.errors[0]


# --- Rename Category Tests ---


def test_rename_category_updates_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.rename_category("travel", "trips")

    assert result.success is True
    assert result.operation == "rename"
    assert not tool.taxonomy.is_valid_key("travel")
    assert tool.taxonomy.is_valid_key("trips")


def test_rename_category_updates_database() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    tool.rename_category("travel", "trips")

    old_id = db.get_category_id_by_key("travel")
    new_id = db.get_category_id_by_key("trips")
    assert old_id is None
    assert new_id is not None


def test_rename_category_updates_children_parent_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    tool.rename_category("food", "meals")

    groceries = tool.taxonomy.get("food.groceries")
    assert groceries is not None
    assert groceries.parent_key == "meals"


def test_rename_category_fails_for_nonexistent_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.rename_category("nonexistent", "new")

    assert result.success is False
    assert "does not exist" in result.errors[0]


def test_rename_category_fails_for_existing_new_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.rename_category("food", "travel")

    assert result.success is False
    assert "already exists" in result.errors[0]


# --- Merge Categories Tests ---


def test_merge_categories_removes_sources() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.merge_categories(["food.restaurants"], "food.groceries")

    assert result.success is True
    assert result.operation == "merge"
    assert not tool.taxonomy.is_valid_key("food.restaurants")
    assert tool.taxonomy.is_valid_key("food.groceries")


def test_merge_categories_reassigns_transactions() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    restaurants_id = db.get_category_id_by_key("food.restaurants")
    assert restaurants_id is not None
    txn = db.insert_transaction(
        {
            "external_id": "ext_1",
            "source": "PLAID",
            "account_id": "acc_1",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1000,
            "currency": "USD",
            "category_id": restaurants_id,
        }
    )

    result = tool.merge_categories(["food.restaurants"], "food.groceries")

    assert result.success is True
    assert result.affected_transaction_count == 1

    refreshed = db.fetch_transactions_by_ids_preserving_order([txn.transaction_id])
    groceries_id = db.get_category_id_by_key("food.groceries")
    assert refreshed[0].category_id == groceries_id


def test_get_transactions_by_category_id_eager_loads_plaid_transaction() -> None:
    db = create_db()
    create_sample_taxonomy(db)
    restaurants_id = db.get_category_id_by_key("food.restaurants")
    assert restaurants_id is not None
    db.insert_transaction(
        {
            "external_id": "ext_eager",
            "source": "PLAID",
            "account_id": "acc_eager",
            "posted_at": date(2024, 1, 15),
            "amount_cents": 1234,
            "currency": "USD",
            "category_id": restaurants_id,
        }
    )

    output = db.get_transactions_by_category_id(restaurants_id)
    expected_output = {"account_id": "acc_eager", "currency": "USD"}

    assert {
        "account_id": output[0].plaid_transaction.account_id,
        "currency": output[0].plaid_transaction.currency,
    } == expected_output


def test_merge_categories_fails_for_nonexistent_source() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.merge_categories(["nonexistent"], "food.groceries")

    assert result.success is False
    assert "not found" in result.errors[0]


def test_merge_categories_fails_for_nonexistent_target() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.merge_categories(["food.restaurants"], "nonexistent")

    assert result.success is False
    assert "not found" in result.errors[0]


def test_merge_categories_preserves_is_verified() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    restaurants_id = db.get_category_id_by_key("food.restaurants")
    assert restaurants_id is not None
    txn = db.insert_transaction(
        {
            "external_id": "ext_verified",
            "source": "PLAID",
            "account_id": "acc_v",
            "posted_at": date(2024, 1, 16),
            "amount_cents": 4200,
            "currency": "USD",
            "category_id": restaurants_id,
            "category_method": "manual",
            "category_assigned_at": date(2024, 1, 16),
            "is_verified": True,
        }
    )

    result = tool.merge_categories(["food.restaurants"], "food.groceries")

    refreshed = db.fetch_transactions_by_ids_preserving_order([txn.transaction_id])
    groceries_id = db.get_category_id_by_key("food.groceries")
    output = {
        "success": result.success,
        "verified_retained": result.verified_retained_count,
        "category_id": refreshed[0].category_id,
        "is_verified": refreshed[0].is_verified,
    }
    expected_output = {
        "success": True,
        "verified_retained": 1,
        "category_id": groceries_id,
        "is_verified": True,
    }

    assert output == expected_output


def test_merge_categories_collapses_multiple_sources_without_llm() -> None:
    """
    Regression: merging multiple sources used to call the unconstrained LLM
    categorizer. The LLM could pick a sibling source (about-to-be-deleted)
    as the new home, and the subsequent Category delete would null only the
    FK column, violating ck_derived_transactions_category_provenance_consistency.
    Merge must now reassign every source txn directly to target without
    consulting the categorizer.
    """
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    # categorizer left unconfigured on purpose: any call to it would raise
    # AttributeError, proving the merge path no longer touches it.
    raise_on_use = MagicMock()
    raise_on_use.categorize.side_effect = AssertionError(
        "merge_categories must not invoke the categorizer"
    )
    raise_on_use.categorize_constrained.side_effect = AssertionError(
        "merge_categories must not invoke the categorizer"
    )
    tool = MigrationTool(db, taxonomy, cast("Categorizer", raise_on_use))

    restaurants_id = db.get_category_id_by_key("food.restaurants")
    travel_id = db.get_category_id_by_key("travel")
    assert restaurants_id is not None
    assert travel_id is not None
    txn_a = db.insert_transaction(
        {
            "external_id": "ext_multi_a",
            "source": "PLAID",
            "account_id": "acc_m",
            "posted_at": date(2024, 1, 17),
            "amount_cents": 1000,
            "currency": "USD",
            "category_id": restaurants_id,
        }
    )
    txn_b = db.insert_transaction(
        {
            "external_id": "ext_multi_b",
            "source": "PLAID",
            "account_id": "acc_m",
            "posted_at": date(2024, 1, 18),
            "amount_cents": 2000,
            "currency": "USD",
            "category_id": travel_id,
        }
    )

    result = tool.merge_categories(["food.restaurants", "travel"], "food.groceries")

    refreshed = db.fetch_transactions_by_ids_preserving_order(
        [txn_a.transaction_id, txn_b.transaction_id]
    )
    groceries_id = db.get_category_id_by_key("food.groceries")
    output = {
        "success": result.success,
        "operation": result.operation,
        "affected": result.affected_transaction_count,
        "category_ids": [t.category_id for t in refreshed],
        "food_restaurants_present": tool.taxonomy.is_valid_key("food.restaurants"),
        "travel_present": tool.taxonomy.is_valid_key("travel"),
    }
    expected_output = {
        "success": True,
        "operation": "merge",
        "affected": 2,
        "category_ids": [groceries_id, groceries_id],
        "food_restaurants_present": False,
        "travel_present": False,
    }

    assert output == expected_output


# --- Split Category Tests ---


def test_split_category_creates_targets_and_removes_source() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.split_category(
        "food.groceries",
        [
            ("food.supermarket", "Supermarket", None),
            ("food.convenience", "Convenience Store", "Quick stops"),
        ],
    )

    assert result.success is True
    assert result.operation == "split"
    assert not tool.taxonomy.is_valid_key("food.groceries")
    assert tool.taxonomy.is_valid_key("food.supermarket")
    assert tool.taxonomy.is_valid_key("food.convenience")


def test_split_category_new_categories_in_database() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    tool.split_category(
        "food.groceries",
        [
            ("food.supermarket", "Supermarket", None),
        ],
    )

    supermarket_id = db.get_category_id_by_key("food.supermarket")
    assert supermarket_id is not None
    old_id = db.get_category_id_by_key("food.groceries")
    assert old_id is None


def test_split_category_fails_for_nonexistent_source() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.split_category("nonexistent", [("a", "A", None)])

    assert result.success is False
    assert "not found" in result.errors[0]


def test_split_category_fails_for_category_with_children() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.split_category("food", [("meals", "Meals", None)])

    assert result.success is False
    assert "has children" in result.errors[0]


def test_split_category_fails_for_existing_target_key() -> None:
    db = create_db()
    taxonomy = create_sample_taxonomy(db)
    categorizer = create_mock_categorizer()
    tool = MigrationTool(db, taxonomy, categorizer)

    result = tool.split_category(
        "food.groceries",
        [("food.restaurants", "Duplicate", None)],
    )

    assert result.success is False
    assert "already exists" in result.errors[0]
