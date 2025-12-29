from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TypedDict, cast

from yaml import safe_load

from transactoid.infra.db.facade import DB, CategoryRow


class RawCategoryRecord(TypedDict, total=False):
    key: str
    name: str
    description: str | None
    parent_key: str | None


class RawTaxonomyDoc(TypedDict, total=False):
    categories: list[RawCategoryRecord]


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    name: str
    description: str | None
    parent_key: str | None


def _load_yaml(path: Path) -> RawTaxonomyDoc:
    if not path.exists():
        raise FileNotFoundError(f"taxonomy yaml not found at {path}")

    with path.open("r", encoding="utf-8") as handle:
        loaded: object = safe_load(handle)

    if loaded is None:
        return {"categories": []}

    if not isinstance(loaded, dict):
        raise ValueError("taxonomy yaml must be a mapping with a 'categories' key")

    return cast(RawTaxonomyDoc, loaded)


def _extract_category_records(raw: RawTaxonomyDoc) -> list[RawCategoryRecord]:
    """Extract raw category records from the loaded YAML, enforcing list shape."""
    records_raw = raw.get("categories")
    if records_raw is None:
        return []
    if not isinstance(records_raw, list):
        raise ValueError("'categories' must be a list")
    return list(records_raw)


def _validate_and_normalize_record(
    record: RawCategoryRecord,
    *,
    position: int,
) -> CategoryConfig:
    """Validate a raw record and convert it into a CategoryConfig."""
    key = record.get("key")
    name = record.get("name")
    description = record.get("description")
    parent_key = record.get("parent_key")

    if not isinstance(key, str) or not key:
        raise ValueError(
            f"category at position {position} is missing a non-empty 'key'"
        )
    if not isinstance(name, str) or not name:
        raise ValueError(f"category '{key}' must define a non-empty 'name'")
    if description is not None and not isinstance(description, str):
        raise ValueError(f"category '{key}' has invalid 'description'")
    if parent_key is not None and not isinstance(parent_key, str):
        raise ValueError(f"category '{key}' has invalid 'parent_key'")

    return CategoryConfig(
        key=key,
        name=name,
        description=description,
        parent_key=parent_key,
    )


def _validate_no_duplicate_keys(configs: Iterable[CategoryConfig]) -> None:
    seen: set[str] = set()
    for cfg in configs:
        if cfg.key in seen:
            raise ValueError(f"duplicate category key '{cfg.key}' encountered")
        seen.add(cfg.key)


def _validate_parent_relationships(configs: list[CategoryConfig]) -> None:
    """Ensure parents exist and are only top-level (two-level taxonomy)."""
    config_map = {config.key: config for config in configs}
    for config in configs:
        if config.parent_key is None:
            continue
        parent = config_map.get(config.parent_key)
        if parent is None:
            raise ValueError(
                f"category '{config.key}' references unknown "
                f"parent '{config.parent_key}'"
            )
        if parent.parent_key is not None:
            raise ValueError(
                f"category '{config.key}' references non-root "
                f"parent '{config.parent_key}'"
            )


def _order_parent_child(configs: Iterable[CategoryConfig]) -> list[CategoryConfig]:
    """Return a list ordered so that each parent appears immediately
    before its children."""
    configs_list = list(configs)
    ordered: list[CategoryConfig] = []
    children_by_parent: dict[str, list[CategoryConfig]] = {}
    for config in configs_list:
        if config.parent_key is None:
            ordered.append(config)
        else:
            children_by_parent.setdefault(config.parent_key, []).append(config)
    hierarchy: list[CategoryConfig] = []
    for config in ordered:
        hierarchy.append(config)
        hierarchy.extend(children_by_parent.get(config.key, []))
    used_keys = {config.key for config in hierarchy}
    for config in configs_list:
        if config.key not in used_keys:
            hierarchy.append(config)
    return hierarchy


def _parse_categories(raw: RawTaxonomyDoc) -> list[CategoryConfig]:
    """High-level parser: extract → validate → normalize → order."""
    records = _extract_category_records(raw)
    configs = [
        _validate_and_normalize_record(record, position=i)
        for i, record in enumerate(records, start=1)
    ]
    _validate_no_duplicate_keys(configs)
    _validate_parent_relationships(configs)
    return _order_parent_child(configs)


def load_categories(yaml_path: Path | str) -> list[CategoryConfig]:
    """
    Load and validate taxonomy categories from a YAML file.
    """

    path = Path(yaml_path)
    raw = _load_yaml(path)
    return _parse_categories(raw)


def _categories_as_rows(
    categories: Iterable[CategoryConfig],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for category in categories:
        rows.append(
            {
                "key": category.key,
                "name": category.name,
                "description": category.description,
                "parent_key": category.parent_key,
            }
        )
    return rows


def _build_category_rows_with_parent_ids(
    configs: Iterable[CategoryConfig],
) -> list[CategoryRow]:
    """
    Build CategoryRow entries with assigned category_id and resolved parent_id
    given validated and ordered CategoryConfig entries.
    """
    rows: list[CategoryRow] = []
    key_to_id: dict[str, int] = {}
    next_id = 1
    for cfg in configs:
        row: CategoryRow = {
            "category_id": next_id,
            "parent_id": None,
            "key": cfg.key,
            "name": cfg.name,
            "description": cfg.description,
            "parent_key": cfg.parent_key,
        }
        if cfg.parent_key is not None:
            parent_id = key_to_id.get(cfg.parent_key)
            if parent_id is None:
                raise ValueError(
                    f"parent key '{cfg.parent_key}' must be defined before children"
                )
            row["parent_id"] = parent_id
        key_to_id[cfg.key] = next_id
        rows.append(row)
        next_id += 1
    return rows


def seed_taxonomy_from_yaml(db: DB, yaml_path: Path | str) -> list[CategoryConfig]:
    """
    Load categories from ``yaml_path`` and replace existing entries in ``db``.
    Returns the validated category configurations that were applied.
    """

    categories = load_categories(yaml_path)
    rows = _build_category_rows_with_parent_ids(categories)
    db.replace_categories_rows(rows)
    return categories


def main(yaml_path: str = "configs/taxonomy.yaml") -> None:
    """
    CLI entrypoint for seeding taxonomy categories.

    The database URL is read from ``DATABASE_URL``. If not provided, an
    in-memory SQLite URL is used as a placeholder.
    """

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
    db = DB(db_url)
    categories = seed_taxonomy_from_yaml(db, yaml_path)
    print(f"Seeded {len(categories)} categories from {yaml_path} into {db_url}")


if __name__ == "__main__":
    main()
