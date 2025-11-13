from __future__ import annotations

import json
from pathlib import Path

from yaml import safe_load

from services.taxonomy import CategoryNode, Taxonomy

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
    prompt_json = json.dumps(prompt, sort_keys=True)

    expected_prompt = json.dumps(
        {
            "include_rules": True,
            "nodes": [
                {
                    "key": "food",
                    "name": "Food",
                    "description": "All food spend",
                    "parent_key": None,
                    "rules": None,
                },
                {
                    "key": "food.groceries",
                    "name": "Groceries",
                    "description": None,
                    "parent_key": "food",
                    "rules": ["grocery"],
                },
            ],
        },
        sort_keys=True,
    )

    assert prompt_json == expected_prompt


def test_path_str_formats_two_level_hierarchy() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    full_path = taxonomy.path_str("food.groceries")

    assert full_path == "Food > Groceries"


def test_category_id_for_key_uses_db_lookup() -> None:
    taxonomy = Taxonomy.from_nodes(build_sample_nodes())

    fake_db = build_fake_db({"food.groceries": 10, "travel.flights": 20})

    groceries_id = taxonomy.category_id_for_key(fake_db, "food.groceries")
    missing_id = taxonomy.category_id_for_key(fake_db, "food.restaurants")

    assert groceries_id == 10
    assert missing_id is None


def test_from_db_converts_categories_to_nodes() -> None:
    db = build_fake_db_for_from_db()
    taxonomy = Taxonomy.from_db(db)
    nodes = {node.key: node for node in taxonomy.all_nodes()}

    assert nodes["food"].parent_key is None
    assert nodes["food.groceries"].rules == ["grocery", "supermarket"]


# Helpers (readable setup)


def build_sample_nodes() -> list[CategoryNode]:
    with SAMPLE_TAXONOMY_PATH.open("r", encoding="utf-8") as taxonomy_file:
        payload = safe_load(taxonomy_file) or {}

    categories_data = payload.get("categories", [])
    if not isinstance(categories_data, list):
        raise ValueError("sample taxonomy fixture must define a categories list")
    nodes: list[CategoryNode] = []

    for category in categories_data:
        nodes.append(
            CategoryNode(
                key=category["key"],
                name=category["name"],
                description=category.get("description"),
                parent_key=category.get("parent_key"),
                rules=category.get("rules"),
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
        self._rows = [
            {
                "key": "food",
                "name": "Food",
                "description": "All food spend",
                "parent_key": None,
                "rules": None,
            },
            {
                "key": "food.groceries",
                "name": "Groceries",
                "description": None,
                "parent_key": "food",
                "rules": ["grocery", "supermarket"],
            },
            {
                "key": "travel",
                "name": "Travel",
                "description": None,
                "parent_key": None,
                "rules": None,
            },
        ]

    def fetch_categories(self) -> list[dict[str, object]]:
        return self._rows


def build_fake_db_for_from_db() -> FakeDBForFromDB:
    return FakeDBForFromDB()
