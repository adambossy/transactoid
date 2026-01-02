from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from yaml import safe_load

from transactoid.taxonomy.core import CategoryNode, Taxonomy
from transactoid.taxonomy.loader import load_taxonomy_from_db

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB


class RawCategory(TypedDict):
    key: str
    name: str
    description: str | None
    parent_key: str | None


class RawTaxonomy(TypedDict, total=False):
    categories: list[RawCategory]


SAMPLE_TAXONOMY_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "sample_taxonomy.yaml"
)


def test_from_nodes_populates_maps() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    food = taxonomy.get("food")
    children = taxonomy.children("food")

    assert food is not None
    assert food.name == "Food"
    assert {child.key for child in children} == {"food.groceries", "food.restaurants"}


def test_is_valid_key_handles_known_and_unknown() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    valid = taxonomy.is_valid_key("food.groceries")
    invalid = taxonomy.is_valid_key("unknown.key")

    assert valid is True
    assert invalid is False


def test_parent_and_children_relationships() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    parent = taxonomy.parent("food.groceries")
    children = taxonomy.children("food")

    assert parent is not None and parent.key == "food"
    assert {child.key for child in children} == {"food.groceries", "food.restaurants"}


def test_parents_returns_only_top_level_nodes() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    parents = taxonomy.parents()

    assert {node.key for node in parents} == {"food", "travel"}


def test_all_nodes_returns_sorted_list() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    all_keys = [node.key for node in taxonomy.all_nodes()]

    assert all_keys == [
        "food",
        "food.groceries",
        "food.restaurants",
        "travel",
        "travel.flights",
    ]


def test_to_prompt_includes_requested_keys() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    prompt = taxonomy.to_prompt(include_keys={"food", "food.groceries"})

    expected_prompt = {
        "nodes": [
            {
                "key": "food",
                "name": "Food",
                "description": "All food spend",
                "parent_key": None,
            },
            {
                "key": "food.groceries",
                "name": "Groceries",
                "description": None,
                "parent_key": "food",
            },
        ],
    }

    assert prompt == expected_prompt


def test_path_str_formats_two_level_hierarchy() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    full_path = taxonomy.path_str("food.groceries")

    assert full_path == "Food > Groceries"


def test_category_id_for_key_uses_db_lookup() -> None:
    from transactoid.taxonomy.loader import get_category_id

    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    fake_db = cast("DB", build_fake_db({"food.groceries": 10, "travel.flights": 20}))

    groceries_id = get_category_id(fake_db, taxonomy, "food.groceries")
    missing_id = get_category_id(fake_db, taxonomy, "food.restaurants")

    assert groceries_id == 10
    assert missing_id is None


def test_from_db_converts_categories_to_nodes() -> None:
    db = cast("DB", build_fake_db_for_from_db())
    taxonomy = load_taxonomy_from_db(db)
    nodes = {node.key: node for node in taxonomy.all_nodes()}

    assert nodes["food"].parent_key is None
    assert nodes["food.groceries"].parent_key == "food"


# Helpers (readable setup)


def build_sample_nodes() -> list[CategoryNode]:
    with SAMPLE_TAXONOMY_PATH.open("r", encoding="utf-8") as taxonomy_file:
        raw_data = cast(RawTaxonomy | None, safe_load(taxonomy_file))

    if raw_data is None:
        payload: RawTaxonomy = {"categories": []}
    else:
        payload = raw_data

    categories: list[RawCategory] = payload.get("categories", [])

    nodes: list[CategoryNode] = []

    for category in categories:
        nodes.append(
            CategoryNode(
                key=category["key"],
                name=category["name"],
                description=category.get("description"),
                parent_key=category.get("parent_key"),
            )
        )

    return nodes


class FakeDB:
    def __init__(self, key_to_id: dict[str, int]) -> None:
        self._key_to_id = key_to_id

    def get_category_id_by_key(self, key: str) -> int | None:
        return self._key_to_id.get(key)

    def fetch_categories(self) -> list[dict[str, object]]:
        raise NotImplementedError("Only used in build_fake_db_for_from_db")


def build_fake_db(mapping: dict[str, int]) -> FakeDB:
    return FakeDB(mapping)


class FakeDBForFromDB(FakeDB):
    def __init__(self) -> None:
        super().__init__({})
        self._rows: list[dict[str, object]] = [
            {
                "key": "food",
                "name": "Food",
                "description": "All food spend",
                "parent_key": None,
            },
            {
                "key": "food.groceries",
                "name": "Groceries",
                "description": None,
                "parent_key": "food",
            },
            {
                "key": "travel",
                "name": "Travel",
                "description": None,
                "parent_key": None,
            },
        ]

    def fetch_categories(self) -> list[dict[str, object]]:
        return self._rows


def build_fake_db_for_from_db() -> FakeDBForFromDB:
    return FakeDBForFromDB()


# --- Migration method tests ---


def test_add_category_creates_new_root_category() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.add_category(
        "health", "Health", None, "Healthcare spending"
    )

    assert new_taxonomy.is_valid_key("health")
    node = new_taxonomy.get("health")
    assert node is not None
    assert node.name == "Health"
    assert node.description == "Healthcare spending"
    assert node.parent_key is None


def test_add_category_creates_new_child_category() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.add_category("food.dining", "Dining Out", "food")

    assert new_taxonomy.is_valid_key("food.dining")
    node = new_taxonomy.get("food.dining")
    assert node is not None
    assert node.parent_key == "food"


def test_add_category_raises_for_duplicate_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="already exists"):
        taxonomy.add_category("food", "Duplicate", None)


def test_add_category_raises_for_nonexistent_parent() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="does not exist"):
        taxonomy.add_category("foo.bar", "Bar", "foo")


def test_add_category_raises_for_non_root_parent() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="not a root category"):
        taxonomy.add_category("food.groceries.organic", "Organic", "food.groceries")


def test_remove_category_removes_leaf_category() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.remove_category("food.groceries")

    assert not new_taxonomy.is_valid_key("food.groceries")
    assert new_taxonomy.is_valid_key("food")


def test_remove_category_raises_for_nonexistent_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="does not exist"):
        taxonomy.remove_category("nonexistent")


def test_remove_category_raises_for_category_with_children() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="has children"):
        taxonomy.remove_category("food")


def test_rename_category_updates_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.rename_category("food", "meals")

    assert not new_taxonomy.is_valid_key("food")
    assert new_taxonomy.is_valid_key("meals")
    node = new_taxonomy.get("meals")
    assert node is not None
    assert node.name == "Food"  # Name stays the same


def test_rename_category_updates_children_parent_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.rename_category("food", "meals")

    groceries = new_taxonomy.get("food.groceries")
    assert groceries is not None
    assert groceries.parent_key == "meals"


def test_rename_category_raises_for_nonexistent_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="does not exist"):
        taxonomy.rename_category("nonexistent", "new")


def test_rename_category_raises_for_existing_new_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="already exists"):
        taxonomy.rename_category("food", "travel")


def test_merge_categories_removes_sources() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.merge_categories(["food.restaurants"], "food.groceries")

    assert not new_taxonomy.is_valid_key("food.restaurants")
    assert new_taxonomy.is_valid_key("food.groceries")


def test_merge_categories_raises_for_empty_sources() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="cannot be empty"):
        taxonomy.merge_categories([], "food.groceries")


def test_merge_categories_raises_for_nonexistent_target() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="does not exist"):
        taxonomy.merge_categories(["food.groceries"], "nonexistent")


def test_merge_categories_raises_for_source_same_as_target() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="cannot be the same"):
        taxonomy.merge_categories(["food.groceries"], "food.groceries")


def test_split_category_creates_targets_and_removes_source() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    new_taxonomy = taxonomy.split_category(
        "food.groceries",
        [
            ("food.supermarket", "Supermarket", None),
            ("food.convenience", "Convenience Store", "Quick stops"),
        ],
    )

    assert not new_taxonomy.is_valid_key("food.groceries")
    assert new_taxonomy.is_valid_key("food.supermarket")
    assert new_taxonomy.is_valid_key("food.convenience")

    supermarket = new_taxonomy.get("food.supermarket")
    assert supermarket is not None
    assert supermarket.parent_key == "food"

    convenience = new_taxonomy.get("food.convenience")
    assert convenience is not None
    assert convenience.description == "Quick stops"


def test_split_category_raises_for_nonexistent_source() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="does not exist"):
        taxonomy.split_category("nonexistent", [("a", "A", None)])


def test_split_category_raises_for_empty_targets() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="at least one target"):
        taxonomy.split_category("food.groceries", [])


def test_split_category_raises_for_existing_target_key() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="already exists"):
        taxonomy.split_category(
            "food.groceries",
            [("food.restaurants", "Restaurants", None)],
        )


def test_split_category_raises_for_source_with_children() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    import pytest

    with pytest.raises(ValueError, match="has children"):
        taxonomy.split_category(
            "food",
            [("meals", "Meals", None)],
        )
