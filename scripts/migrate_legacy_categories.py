from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re

from dotenv import load_dotenv
import typer
import yaml

from services.db import DB, CategoryRow

app = typer.Typer(
    help=(
        "Map legacy Fire Ant category rows to the current two-level taxonomy "
        "and optionally persist the result."
    )
)

DEFAULT_INPUT_PATH = Path("fa_categories_rows.csv")

INPUT_PATH_OPTION = typer.Option(
    DEFAULT_INPUT_PATH,
    "--input",
    "-i",
    help="Path to the exported legacy categories CSV.",
)
OUTPUT_YAML_OPTION = typer.Option(
    None,
    "--output-yaml",
    help="Optional path to write the converted taxonomy YAML.",
)
APPLY_TO_DB_OPTION = typer.Option(
    False,
    "--apply",
    help="Persist the mapped categories into the configured database.",
)
INCLUDE_INACTIVE_OPTION = typer.Option(
    False,
    "--include-inactive",
    help="Keep legacy rows marked as inactive instead of filtering them out.",
)
DATABASE_URL_OPTION = typer.Option(
    None,
    "--database-url",
    help="Override DATABASE_URL when applying the migration.",
)


@dataclass(frozen=True, slots=True)
class LegacyCategory:
    code: str
    display_name: str
    parent_code: str | None
    is_active: bool
    sort_order: int | None


CSV_COLUMNS = {
    "code",
    "display_name",
    "is_active",
    "sort_order",
    "created_at",
    "updated_at",
    "parent_code",
}


def load_legacy_categories(
    csv_path: Path,
    *,
    include_inactive: bool = False,
) -> list[LegacyCategory]:
    if not csv_path.exists():
        raise FileNotFoundError(f"legacy categories CSV not found at {csv_path}")

    records: list[LegacyCategory] = []
    seen_codes: set[str] = set()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("legacy categories CSV is missing a header row")
        missing = CSV_COLUMNS - set(reader.fieldnames)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"legacy CSV is missing required columns: {missing_list}")

        for idx, row in enumerate(reader, start=2):
            code = (row.get("code") or "").strip()
            if not code:
                raise ValueError(f"row {idx} is missing a legacy code")
            if code in seen_codes:
                raise ValueError(f"duplicate legacy code '{code}' detected (row {idx})")
            display_name = (row.get("display_name") or "").strip()
            if not display_name:
                raise ValueError(f"row {idx} is missing a display name")

            parent_code = (row.get("parent_code") or "").strip() or None

            raw_is_active = (row.get("is_active") or "").strip().lower()
            is_active = raw_is_active in {"t", "true", "1", "yes"}
            if not include_inactive and not is_active:
                continue

            sort_order_str = (row.get("sort_order") or "").strip()
            sort_order = int(sort_order_str) if sort_order_str else None

            records.append(
                LegacyCategory(
                    code=code,
                    display_name=display_name,
                    parent_code=parent_code,
                    is_active=is_active,
                    sort_order=sort_order,
                )
            )
            seen_codes.add(code)
    return records


def slugify_label(label: str) -> str:
    normalized = (
        label.lower()
        .replace("&", " and ")
        .replace("@", " at ")
        .replace("%", " percent ")
    )
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    slug = re.sub(r"\s+", "_", normalized).strip("_")
    return slug or "category"


def build_slug_map(records: Iterable[LegacyCategory]) -> dict[str, str]:
    slug_map: dict[str, str] = {}
    used: set[str] = set()
    for record in sorted(records, key=lambda rec: rec.code.lower()):
        base_slug = slugify_label(record.code)
        slug = base_slug
        suffix = 2
        while slug in used:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        slug_map[record.code] = slug
        used.add(slug)
    return slug_map


def _sort_key(record: LegacyCategory) -> tuple[int, str]:
    order = record.sort_order if record.sort_order is not None else 10_000
    return (order, record.display_name.lower())


def build_category_rows(
    records: Sequence[LegacyCategory],
    slug_map: Mapping[str, str],
) -> tuple[list[CategoryRow], dict[str, str]]:
    parents = [record for record in records if record.parent_code is None]
    if not parents:
        raise ValueError("no top-level categories detected in legacy data")

    child_lookup: dict[str, list[LegacyCategory]] = {}
    for record in records:
        if record.parent_code:
            child_lookup.setdefault(record.parent_code, []).append(record)

    rows: list[CategoryRow] = []
    key_by_code: dict[str, str] = {}
    id_by_code: dict[str, int] = {}
    next_id = 1
    for parent in sorted(parents, key=_sort_key):
        parent_slug = _slug_for_code(parent.code, slug_map)
        parent_row: CategoryRow = {
            "category_id": next_id,
            "parent_id": None,
            "key": parent_slug,
            "name": parent.display_name,
            "description": None,
            "parent_key": None,
        }
        rows.append(parent_row)
        id_by_code[parent.code] = next_id
        key_by_code[parent.code] = parent_slug
        next_id += 1

        children = child_lookup.get(parent.code, [])
        for child in sorted(children, key=_sort_key):
            child_slug = _slug_for_code(child.code, slug_map)
            child_key = f"{parent_slug}.{child_slug}"
            child_row: CategoryRow = {
                "category_id": next_id,
                "parent_id": id_by_code[parent.code],
                "key": child_key,
                "name": child.display_name,
                "description": None,
                "parent_key": parent_slug,
            }
            rows.append(child_row)
            id_by_code[child.code] = next_id
            key_by_code[child.code] = child_key
            next_id += 1

    _ensure_all_children_attached(child_lookup, id_by_code)
    return rows, key_by_code


def _slug_for_code(code: str, slug_map: Mapping[str, str]) -> str:
    slug = slug_map.get(code)
    if slug is None:
        raise KeyError(f"no slug defined for legacy code '{code}'")
    return slug


def _ensure_all_children_attached(
    child_lookup: Mapping[str, list[LegacyCategory]],
    id_by_code: Mapping[str, int],
) -> None:
    dangling_parents = [code for code in child_lookup if code not in id_by_code]
    if dangling_parents:
        joined = ", ".join(sorted(dangling_parents))
        raise ValueError(
            f"legacy categories reference parents that were not imported: {joined}"
        )


def _rows_to_yaml_payload(rows: Sequence[CategoryRow]) -> dict[str, object]:
    return {
        "categories": [
            {
                "key": row["key"],
                "name": row["name"],
                "description": row.get("description"),
                "parent_key": row.get("parent_key"),
            }
            for row in rows
        ]
    }


def write_taxonomy_yaml(rows: Sequence[CategoryRow], output_path: Path) -> None:
    payload = _rows_to_yaml_payload(rows)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def _print_preview(
    key_by_code: Mapping[str, str],
    rows: Sequence[CategoryRow],
    *,
    preview_count: int = 5,
) -> None:
    typer.echo(f"Total categories generated: {len(rows)}")
    typer.echo(f"Unique legacy codes mapped: {len(key_by_code)}")
    typer.echo("Sample mappings:")
    for code, key in list(key_by_code.items())[:preview_count]:
        typer.echo(f"  • {code} → {key}")


@app.command("migrate")  # type: ignore[misc]
def migrate_command(
    input_path: Path = INPUT_PATH_OPTION,
    output_yaml: Path | None = OUTPUT_YAML_OPTION,
    apply_to_db: bool = APPLY_TO_DB_OPTION,
    include_inactive: bool = INCLUDE_INACTIVE_OPTION,
    database_url: str | None = DATABASE_URL_OPTION,
) -> None:
    """
    Convert `fa_categories_rows.csv` into the two-level taxonomy schema.
    """

    load_dotenv(override=False)
    records = load_legacy_categories(
        input_path,
        include_inactive=include_inactive,
    )
    if not records:
        raise typer.BadParameter("no legacy categories found after filtering")

    slug_map = build_slug_map(records)
    rows, key_by_code = build_category_rows(records, slug_map)

    if output_yaml is not None:
        write_taxonomy_yaml(rows, output_yaml)
        typer.echo(f"Wrote taxonomy YAML to {output_yaml}")

    if apply_to_db:
        db_url = database_url or os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        db = DB(db_url)
        db.replace_categories_rows(rows)
        typer.echo(f"Replaced {len(rows)} categories in {db_url}")
    else:
        typer.echo("Dry run only (database not touched).")

    _print_preview(key_by_code, rows)


def main() -> None:
    app()


__all__ = [
    "LegacyCategory",
    "build_category_rows",
    "build_slug_map",
    "load_legacy_categories",
    "migrate_command",
    "slugify_label",
    "write_taxonomy_yaml",
]


if __name__ == "__main__":
    main()
