"""Tests for the shared taxonomy migration dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import Base, CategoryRow
from transactoid.taxonomy.core import Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.migrate.dispatcher import OPERATIONS, run_migration
from transactoid.tools.migrate.migration_tool import MigrationTool

if TYPE_CHECKING:
    from transactoid.tools.categorize.categorizer_tool import Categorizer


def _create_db() -> DB:
    db = DB("sqlite:///:memory:")
    with db.session() as session:
        assert session.bind is not None
        Base.metadata.create_all(session.bind)
    return db


def _create_sample_taxonomy(db: DB) -> Taxonomy:
    db.replace_categories_rows(
        [
            CategoryRow(
                category_id=1,
                parent_id=None,
                key="food",
                name="Food",
                description=None,
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
                description=None,
                parent_key="food",
                deprecated_at=None,
            ),
        ]
    )
    return load_taxonomy_from_db(db)


def _create_tool() -> MigrationTool:
    db = _create_db()
    taxonomy = _create_sample_taxonomy(db)
    mock = MagicMock()
    mock.categorize = AsyncMock(return_value=[])
    mock.categorize_constrained = AsyncMock(return_value=[])
    return MigrationTool(db, taxonomy, cast("Categorizer", mock))


def test_dispatcher_advertises_supported_operations() -> None:
    output = set(OPERATIONS)
    expected_output = {"add", "remove", "rename", "merge", "split"}
    assert output == expected_output


def test_dispatcher_add_returns_success_dict() -> None:
    tool = _create_tool()

    output = run_migration(
        tool, operation="add", new_key="health", name="Health", parent_key=None
    )

    assert output["success"] is True
    assert output["operation"] == "add"


def test_dispatcher_merge_returns_success_dict() -> None:
    tool = _create_tool()

    output = run_migration(
        tool,
        operation="merge",
        source_keys=["food.restaurants"],
        target_key="food.groceries",
    )

    assert output["success"] is True
    assert output["operation"] == "merge"


def test_dispatcher_unknown_operation_returns_error() -> None:
    tool = _create_tool()

    output = run_migration(tool, operation="bogus")

    expected_output = {
        "success": False,
        "operation": "bogus",
        "errors_first": "Unknown operation: bogus",
    }
    assert {
        "success": output["success"],
        "operation": output["operation"],
        "errors_first": output["errors"][0],
    } == expected_output


def test_dispatcher_merge_missing_args_returns_error() -> None:
    tool = _create_tool()

    output = run_migration(tool, operation="merge", source_keys=None, target_key=None)

    assert output["success"] is False
    assert "source_keys" in output["errors"][0]


def test_dispatcher_split_passes_targets_through() -> None:
    tool = _create_tool()

    output = run_migration(
        tool,
        operation="split",
        source_key="food.groceries",
        targets=[("food.supermarket", "Supermarket", None)],
    )

    assert output["operation"] == "split"
    assert output["success"] is True
