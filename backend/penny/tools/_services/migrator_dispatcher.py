"""Shared dispatcher for taxonomy migration operations.

ACP, MCP, and CLI surfaces all route here so the schema, validation, and
result shape stay in lockstep across surfaces.
"""

from __future__ import annotations

from typing import Any

from penny.tools._services.migrator import MigrationResult, MigrationTool

OPERATIONS: tuple[str, ...] = ("add", "remove", "rename", "merge", "split")


def run_migration(
    migration_tool: MigrationTool,
    *,
    operation: str,
    source_key: str | None = None,
    target_key: str | None = None,
    source_keys: list[str] | None = None,
    targets: list[tuple[str, str, str | None]] | None = None,
    new_key: str | None = None,
    name: str | None = None,
    parent_key: str | None = None,
    description: str | None = None,
    fallback_key: str | None = None,
) -> dict[str, Any]:
    """Dispatch a single taxonomy migration operation and return a result dict.

    Surface-specific layers should validate types/required-fields, then call
    this. The returned shape is stable across surfaces.
    """
    if operation == "add":
        if not new_key or not name or not description:
            return _error(
                "add",
                "add requires new_key, name, and description "
                "(define the category, including examples and exclusions)",
            )
        result = migration_tool.add_category(new_key, name, parent_key, description)
    elif operation == "remove":
        if not source_key:
            return _error("remove", "remove requires source_key")
        result = migration_tool.remove_category(source_key, fallback_key)
    elif operation == "rename":
        if not source_key or not new_key:
            return _error("rename", "rename requires source_key and new_key")
        result = migration_tool.rename_category(source_key, new_key)
    elif operation == "merge":
        if not source_keys or not target_key:
            return _error("merge", "merge requires source_keys and target_key")
        result = migration_tool.merge_categories(source_keys, target_key)
    elif operation == "split":
        if not source_key or not targets:
            return _error("split", "split requires source_key and targets")
        result = migration_tool.split_category(source_key, targets)
    else:
        return _error(operation or "unknown", f"Unknown operation: {operation}")

    return _result_to_dict(result)


def _error(operation: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "operation": operation,
        "affected_transactions": 0,
        "recategorized": 0,
        "verified_retained": 0,
        "verified_demoted": 0,
        "errors": [message],
        "summary": message,
    }


def _result_to_dict(result: MigrationResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "operation": result.operation,
        "affected_transactions": result.affected_transaction_count,
        "recategorized": result.recategorized_count,
        "verified_retained": result.verified_retained_count,
        "verified_demoted": result.verified_demoted_count,
        "errors": result.errors,
        "summary": result.summary,
    }
