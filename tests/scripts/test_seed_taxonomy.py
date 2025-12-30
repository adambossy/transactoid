from __future__ import annotations

from pathlib import Path

import pytest

from scripts.seed_taxonomy import load_categories, seed_taxonomy_from_yaml
from transactoid.adapters.db.facade import DB, CategoryRow


def test_seed_taxonomy_applies_fixture_to_db(tmp_path: Path) -> None:
    from transactoid.adapters.db.models import Base

    yaml_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "sample_taxonomy.yaml"
    )
    db = DB("sqlite:///:memory:")

    # Create tables
    with db.session() as session:
        assert session.bind is not None
        Base.metadata.create_all(session.bind)

    categories = seed_taxonomy_from_yaml(db, yaml_path)

    assert [category.key for category in categories] == [
        "food",
        "food.groceries",
        "food.restaurants",
        "travel",
        "travel.flights",
    ]

    stored: list[CategoryRow] = db.fetch_categories()
    assert len(stored) == 5

    keyed = {row["key"]: row for row in stored}
    food = keyed["food"]
    groceries = keyed["food.groceries"]
    restaurants = keyed["food.restaurants"]
    travel = keyed["travel"]
    flights = keyed["travel.flights"]

    assert food["parent_id"] is None
    assert groceries["parent_id"] == food["category_id"]
    assert restaurants["parent_id"] == food["category_id"]
    assert travel["parent_id"] is None
    assert flights["parent_id"] == travel["category_id"]


def test_load_categories_validates_unknown_parent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "invalid_taxonomy.yaml"
    yaml_path.write_text(
        "categories:\n  - key: child\n    name: Child\n    parent_key: missing\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown parent 'missing'"):
        load_categories(yaml_path)
