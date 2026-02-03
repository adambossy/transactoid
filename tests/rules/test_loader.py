from __future__ import annotations

from pathlib import Path

import pytest

from transactoid.rules.loader import MerchantRulesLoader
from transactoid.taxonomy.core import CategoryNode, Taxonomy


def create_taxonomy() -> Taxonomy:
    """Create a sample taxonomy for testing."""
    nodes = [
        CategoryNode(key="food", name="Food", description=None, parent_key=None),
        CategoryNode(
            key="food.groceries",
            name="Groceries",
            description=None,
            parent_key="food",
        ),
        CategoryNode(
            key="transportation",
            name="Transportation",
            description=None,
            parent_key=None,
        ),
        CategoryNode(
            key="transportation.fuel",
            name="Fuel",
            description=None,
            parent_key="transportation",
        ),
    ]
    return Taxonomy.from_nodes(nodes)


def create_rules_file(tmp_path: Path, content: str) -> Path:
    """Create a merchant rules file with the given content."""
    rules_path = tmp_path / "merchant-rules.md"
    rules_path.write_text(content)
    return rules_path


# --- Load Tests ---


def test_load_returns_file_content(tmp_path: Path) -> None:
    content = "# Test Rules\n\nSome rules here."
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)

    result = loader.load()

    assert result == content


def test_load_returns_empty_string_for_missing_file(tmp_path: Path) -> None:
    rules_path = tmp_path / "nonexistent.md"
    loader = MerchantRulesLoader(rules_path)

    result = loader.load()

    assert result == ""


def test_load_caches_content(tmp_path: Path) -> None:
    content = "# Rules"
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)

    first_load = loader.load()
    rules_path.write_text("# Updated Rules")
    second_load = loader.load()

    assert first_load == content
    assert second_load == content


# --- Validation Tests ---


def test_load_validates_category_keys_with_taxonomy(tmp_path: Path) -> None:
    content = """# Rules

## Rule: Costco Gas

**Category:** `transportation.fuel`

Description here.
"""
    rules_path = create_rules_file(tmp_path, content)
    taxonomy = create_taxonomy()
    loader = MerchantRulesLoader(rules_path, taxonomy=taxonomy)

    result = loader.load()

    assert result == content


def test_load_raises_for_invalid_category_key(tmp_path: Path) -> None:
    content = """# Rules

## Rule: Invalid

**Category:** `invalid.category`

Description here.
"""
    rules_path = create_rules_file(tmp_path, content)
    taxonomy = create_taxonomy()
    loader = MerchantRulesLoader(rules_path, taxonomy=taxonomy)

    with pytest.raises(ValueError) as exc_info:
        loader.load()

    assert "invalid.category" in str(exc_info.value)


def test_load_without_taxonomy_skips_validation(tmp_path: Path) -> None:
    content = """# Rules

## Rule: Invalid

**Category:** `invalid.category`

Description here.
"""
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)

    result = loader.load()

    assert result == content


# --- Extract Category Keys Tests ---


def test_extract_category_keys_finds_all_keys(tmp_path: Path) -> None:
    content = """# Rules

## Rule: One

**Category:** `food.groceries`

## Rule: Two

**Category:** `transportation.fuel`
"""
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    keys = loader.extract_category_keys()

    assert keys == ["food.groceries", "transportation.fuel"]


def test_extract_category_keys_returns_empty_for_no_keys(tmp_path: Path) -> None:
    content = "# Rules\n\nNo categories here."
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    keys = loader.extract_category_keys()

    assert keys == []


def test_extract_category_keys_loads_file_if_not_loaded(tmp_path: Path) -> None:
    content = "**Category:** `food.groceries`"
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)

    keys = loader.extract_category_keys()

    assert keys == ["food.groceries"]


# --- Update Category Keys Tests ---


def test_update_category_keys_replaces_keys(tmp_path: Path) -> None:
    content = """# Rules

## Rule: Test

**Category:** `old.key`

Description here.
"""
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    loader.update_category_keys({"old.key": "new.key"})

    updated_content = rules_path.read_text()
    assert "**Category:** `new.key`" in updated_content
    assert "old.key" not in updated_content


def test_update_category_keys_replaces_multiple_keys(tmp_path: Path) -> None:
    content = """# Rules

## Rule: One

**Category:** `key.one`

## Rule: Two

**Category:** `key.two`
"""
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    loader.update_category_keys({"key.one": "new.one", "key.two": "new.two"})

    updated_content = rules_path.read_text()
    assert "**Category:** `new.one`" in updated_content
    assert "**Category:** `new.two`" in updated_content


def test_update_category_keys_preserves_unmatched_keys(tmp_path: Path) -> None:
    content = """# Rules

## Rule: Test

**Category:** `unchanged.key`

Description here.
"""
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    loader.update_category_keys({"other.key": "new.key"})

    updated_content = rules_path.read_text()
    assert "**Category:** `unchanged.key`" in updated_content


def test_update_category_keys_does_nothing_for_missing_file(tmp_path: Path) -> None:
    rules_path = tmp_path / "nonexistent.md"
    loader = MerchantRulesLoader(rules_path)

    loader.update_category_keys({"old": "new"})

    assert not rules_path.exists()


def test_update_category_keys_updates_cached_content(tmp_path: Path) -> None:
    content = "**Category:** `old.key`"
    rules_path = create_rules_file(tmp_path, content)
    loader = MerchantRulesLoader(rules_path)
    loader.load()

    loader.update_category_keys({"old.key": "new.key"})

    keys = loader.extract_category_keys()
    assert keys == ["new.key"]


# --- Rules Path Property Test ---


def test_rules_path_returns_configured_path(tmp_path: Path) -> None:
    rules_path = tmp_path / "merchant-rules.md"
    loader = MerchantRulesLoader(rules_path)

    assert loader.rules_path == rules_path
