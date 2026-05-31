"""Taxonomy migration tool — add/remove/rename/merge/split categories."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from ..services import get_migrator
from ..tools._services.migrator_dispatcher import run_migration


@tool
async def migrate_taxonomy(
    operation: str,
    source_key: str | None = None,
    target_key: str | None = None,
    source_keys: list[str] | None = None,
    targets: list[dict[str, str | None]] | None = None,
    new_key: str | None = None,
    name: str | None = None,
    parent_key: str | None = None,
    description: str | None = None,
    fallback_key: str | None = None,
) -> dict[str, Any]:
    """Perform a taxonomy migration: add, remove, rename, merge, or split.

    Required arguments per operation:
      - **add**: new_key, name; optional parent_key, description
      - **remove**: source_key; optional fallback_key (required if the
        category has transactions)
      - **rename**: source_key, new_key
      - **merge**: source_keys, target_key
      - **split**: source_key, targets (list of {key, name, description?})

    Merge bulk-reassigns every source-category transaction to target_key and
    preserves is_verified. Split uses constrained recategorization among
    the new targets via the LLM.
    """
    typed_targets: list[tuple[str, str, str | None]] | None = None
    if targets:
        typed_targets = []
        for target in targets:
            key = target.get("key")
            target_name = target.get("name")
            if not isinstance(key, str) or not isinstance(target_name, str):
                return {
                    "success": False,
                    "operation": operation,
                    "errors": ["each target requires string 'key' and 'name'"],
                    "summary": "Failed: malformed targets",
                }
            tdesc = target.get("description")
            typed_targets.append((key, target_name, tdesc if isinstance(tdesc, str) else None))

    def _run() -> dict[str, Any]:
        return run_migration(
            get_migrator(),
            operation=operation,
            source_key=source_key,
            target_key=target_key,
            source_keys=source_keys,
            targets=typed_targets,
            new_key=new_key,
            name=name,
            parent_key=parent_key,
            description=description,
            fallback_key=fallback_key,
        )

    return await asyncio.to_thread(_run)
