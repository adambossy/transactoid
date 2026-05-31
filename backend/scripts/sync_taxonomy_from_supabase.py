"""Dump the live taxonomy from the prod Supabase DB to ``configs/taxonomy.yaml``.

Reads the source DB from ``$SUPABASE_DATABASE_URL`` (separate from
``$DATABASE_URL`` so it can't be confused with the local SQLite). Writes
parent rows first, then children, with ``parent_id`` resolved to
``parent_key`` so the YAML is portable across DB backends.

Skips soft-deleted categories (``deprecated_at IS NOT NULL``).

Run::

    SUPABASE_DATABASE_URL='postgresql://...' uv run python \\
        scripts/sync_taxonomy_from_supabase.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

_OUT = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"


def main() -> int:
    url = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not url:
        print("ERROR: set SUPABASE_DATABASE_URL to the prod Supabase URL.", file=sys.stderr)
        return 1

    engine = create_engine(url)
    with engine.connect() as conn:
        # category_id -> key map for parent resolution
        id_to_key: dict[int, str] = {}
        rows = conn.execute(
            text(
                "SELECT category_id, key FROM categories "
                "WHERE deprecated_at IS NULL ORDER BY category_id"
            )
        ).fetchall()
        for cid, key in rows:
            id_to_key[cid] = key

        # full rows
        result = conn.execute(
            text(
                "SELECT category_id, parent_id, key, name, description, rules "
                "FROM categories WHERE deprecated_at IS NULL "
                "ORDER BY parent_id NULLS FIRST, key"
            )
        ).fetchall()

    out: list[dict[str, object]] = []
    for cid, parent_id, key, name, description, rules in result:
        out.append(
            {
                "key": key,
                "name": name,
                "parent_key": id_to_key.get(parent_id) if parent_id is not None else None,
                "description": description,
                "rules": rules,
            }
        )

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(out)} categories -> {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
