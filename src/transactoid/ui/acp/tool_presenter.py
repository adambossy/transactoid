"""Tool display presenter for ACP rich tool execution.

Pure-function module that maps (tool_name, arguments, runtime_info) to
(title, kind, content, locations) for both input and output phases.

Based on claude-code-acp's per-tool formatting patterns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import json
from typing import Any

from transactoid.core.runtime.protocol import (
    NamedOutput,
    ToolCallKind,
    ToolRuntimeInfo,
    classify_tool_kind,
)


def _json_default(obj: Any) -> Any:
    """Serialize non-default JSON types used in tool payloads."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dumps_json(payload: Any, *, indent: int = 2) -> str:
    """Serialize tool payloads with Decimal support."""
    return json.dumps(payload, indent=indent, default=_json_default)


@dataclass(frozen=True, slots=True)
class ToolDisplay:
    """Display-ready payload for a tool call phase."""

    title: str
    kind: ToolCallKind
    content: list[dict[str, Any]]
    locations: list[dict[str, Any]]


def present_tool_input(
    tool_name: str,
    arguments: Mapping[str, object],
    runtime_info: ToolRuntimeInfo | None = None,
) -> ToolDisplay:
    """Generate display payload for a tool call's input phase.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments
        runtime_info: Optional runtime metadata (command, cwd, etc.)

    Returns:
        ToolDisplay with title, kind, content blocks, and locations
    """
    kind = classify_tool_kind(tool_name)

    # Per-tool input formatting
    if tool_name == "run_sql":
        return _present_run_sql_input(arguments, kind)
    if tool_name == "sync_transactions":
        return _present_sync_transactions_input(arguments, kind)
    if tool_name == "recategorize_merchant":
        return _present_recategorize_merchant_input(arguments, kind)
    if tool_name == "tag_transactions":
        return _present_tag_transactions_input(arguments, kind)
    if tool_name in ("list_accounts", "list_plaid_accounts"):
        return ToolDisplay(
            title="List connected accounts",
            kind=kind,
            content=[],
            locations=[],
        )
    if tool_name == "connect_new_account":
        return ToolDisplay(
            title="Connect new bank account",
            kind=kind,
            content=[],
            locations=[],
        )
    if tool_name == "scrape_amazon_orders":
        return ToolDisplay(
            title="Scrape Amazon orders",
            kind=kind,
            content=[],
            locations=[],
        )
    if tool_name == "migrate_taxonomy":
        return _present_migrate_taxonomy_input(arguments, kind)
    if tool_name == "generate_chart":
        return _present_generate_chart_input(arguments, kind)
    if tool_name == "upload_artifact":
        artifact_type = arguments.get("artifact_type", "file")
        return ToolDisplay(
            title=f"Upload {artifact_type}",
            kind=kind,
            content=[],
            locations=[],
        )
    if tool_name == "execute_shell" and runtime_info and runtime_info.command:
        locations = []
        if runtime_info.cwd:
            locations.append({"path": runtime_info.cwd})
        return ToolDisplay(
            title=f"`{runtime_info.command}`",
            kind=kind,
            content=[{"type": "text", "text": runtime_info.command}],
            locations=locations,
        )

    # Default: tool name as title, arguments as JSON

    args_json = _dumps_json(dict(arguments))
    return ToolDisplay(
        title=tool_name,
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```json\n{args_json}\n```",
                },
            }
        ],
        locations=[],
    )


def present_tool_output(
    tool_name: str,
    arguments: Mapping[str, object],
    status: str,
    result: dict[str, object] | str,
    named_outputs: list[NamedOutput] | None = None,
    runtime_info: ToolRuntimeInfo | None = None,
) -> ToolDisplay:
    """Generate display payload for a tool call's output phase.

    Args:
        tool_name: Name of the tool
        arguments: Tool arguments (for context)
        status: Execution status ("completed" or "failed")
        result: Tool result payload
        named_outputs: Optional named outputs (stdout, stderr, etc.)
        runtime_info: Optional runtime metadata

    Returns:
        ToolDisplay with title, kind, content blocks, and locations
    """
    kind = classify_tool_kind(tool_name)

    # Per-tool output formatting
    if tool_name == "run_sql":
        return _present_run_sql_output(result, status, kind)
    if tool_name == "sync_transactions":
        return _present_sync_transactions_output(result, status, kind)
    if tool_name == "recategorize_merchant":
        return _present_recategorize_merchant_output(result, status, kind)
    if tool_name == "tag_transactions":
        return _present_tag_transactions_output(result, status, kind)
    if tool_name in ("list_accounts", "list_plaid_accounts"):
        return _present_list_accounts_output(result, status, kind)
    if tool_name == "scrape_amazon_orders":
        return _present_scrape_amazon_orders_output(result, status, kind)
    if tool_name == "generate_chart":
        return _present_generate_chart_output(result, status, kind)
    if tool_name == "execute_shell" and named_outputs:
        return _present_execute_shell_output(named_outputs, status, kind)

    # Error case
    if status == "failed":
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[
                {
                    "type": "content",
                    "content": {
                        "type": "text",
                        "text": f"```\n{error_text}\n```",
                    },
                }
            ],
            locations=[],
        )

    # Default: result as JSON

    result_json = _dumps_json(
        result if isinstance(result, dict) else {"result": result},
    )
    return ToolDisplay(
        title="",
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```json\n{result_json}\n```",
                },
            }
        ],
        locations=[],
    )


# --- Input presenters ---


def _present_run_sql_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present run_sql input with query truncation."""
    query = str(arguments.get("query", "")).strip()
    first_line = query.split("\n")[0]
    title = first_line[:57] + "..." if len(first_line) > 60 else first_line

    return ToolDisplay(
        title=title,
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```sql\n{query}\n```",
                },
            }
        ],
        locations=[],
    )


def _present_sync_transactions_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present sync_transactions input with count."""
    count = arguments.get("count", 250)
    return ToolDisplay(
        title=f"Sync up to {count} transactions",
        kind=kind,
        content=[],
        locations=[],
    )


def _present_recategorize_merchant_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present recategorize_merchant input with merchant and category."""
    merchant_id = arguments.get("merchant_id", "unknown")
    category = arguments.get("category_key", "unknown")
    return ToolDisplay(
        title=f"Recategorize merchant {merchant_id} → {category}",
        kind=kind,
        content=[],
        locations=[],
    )


def _present_tag_transactions_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present tag_transactions input with count and tags."""
    tx_ids = arguments.get("transaction_ids", [])
    tags = arguments.get("tags", [])
    count = len(tx_ids) if isinstance(tx_ids, list) else 0
    tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
    return ToolDisplay(
        title=f"Tag {count} transactions: {tag_str}",
        kind=kind,
        content=[],
        locations=[],
    )


def _present_migrate_taxonomy_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present migrate_taxonomy input with operation."""
    operation = arguments.get("operation", "unknown")
    source_key = arguments.get("source_key", "")
    title = f"{operation} {source_key}".strip()
    return ToolDisplay(
        title=title,
        kind=kind,
        content=[
            {"type": "text", "text": f"Operation: {operation}\nKey: {source_key}"}
        ],
        locations=[],
    )


# --- Output presenters ---


def _present_run_sql_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present run_sql output as JSON or error."""

    if status == "failed":
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[
                {
                    "type": "content",
                    "content": {
                        "type": "text",
                        "text": f"```\n{error_text}\n```",
                    },
                }
            ],
            locations=[],
        )

    result_json = _dumps_json(
        result if isinstance(result, dict) else {"result": result},
    )
    return ToolDisplay(
        title="",
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```json\n{result_json}\n```",
                },
            }
        ],
        locations=[],
    )


def _present_sync_transactions_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present sync_transactions output as summary."""
    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    added = result.get("total_added", 0)
    modified = result.get("total_modified", 0)
    removed = result.get("total_removed", 0)
    summary = f"Added {added}, modified {modified}, removed {removed}"
    return ToolDisplay(
        title="",
        kind=kind,
        content=[{"type": "text", "text": summary}],
        locations=[],
    )


def _present_recategorize_merchant_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present recategorize_merchant output as summary."""
    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    count = result.get("recategorized_count", 0)
    summary = f"Recategorized {count} transactions"
    return ToolDisplay(
        title="",
        kind=kind,
        content=[{"type": "text", "text": summary}],
        locations=[],
    )


def _present_tag_transactions_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present tag_transactions output as summary."""
    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    count = result.get("tagged_count", 0)
    summary = f"Tagged {count} transactions"
    return ToolDisplay(
        title="",
        kind=kind,
        content=[{"type": "text", "text": summary}],
        locations=[],
    )


def _present_list_accounts_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present list_accounts output as JSON."""

    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    result_json = _dumps_json(result)
    return ToolDisplay(
        title="",
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```json\n{result_json}\n```",
                },
            }
        ],
        locations=[],
    )


def _present_scrape_amazon_orders_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present scrape_amazon_orders output as summary."""
    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    orders = result.get("orders_created", 0)
    items = result.get("items_created", 0)
    summary = f"Scraped {orders} orders, {items} items"
    return ToolDisplay(
        title="",
        kind=kind,
        content=[{"type": "text", "text": summary}],
        locations=[],
    )


def _present_execute_shell_output(
    named_outputs: list[NamedOutput],
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present execute_shell output with stdout/stderr."""
    stdout = next((o.text for o in named_outputs if o.name == "stdout"), "")
    stderr = next((o.text for o in named_outputs if o.name == "stderr"), "")

    text = f"```sh\n{stdout}\n```"
    if stderr and stderr.strip():
        text += f"\n\nstderr:\n```\n{stderr}\n```"

    return ToolDisplay(
        title="",
        kind=kind,
        content=[
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": text,
                },
            }
        ],
        locations=[],
    )


def _present_generate_chart_input(
    arguments: Mapping[str, object],
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present generate_chart input with chart type and title."""
    chart_type = str(arguments.get("chart_type", "chart"))
    title = str(arguments.get("title", "Chart"))
    return ToolDisplay(
        title=f"Generate {chart_type} chart: {title}",
        kind=kind,
        content=[],
        locations=[],
    )


def _present_generate_chart_output(
    result: dict[str, object] | str,
    status: str,
    kind: ToolCallKind,
) -> ToolDisplay:
    """Present generate_chart output with ASCII plot and file path."""
    if status == "failed" or isinstance(result, str):
        error_text = (
            result
            if isinstance(result, str)
            else str(result.get("error", "Unknown error"))
        )
        return ToolDisplay(
            title="",
            kind=kind,
            content=[{"type": "text", "text": error_text}],
            locations=[],
        )

    title = str(result.get("title", "Chart"))
    file_path = str(result.get("file_path", ""))
    ascii_plot = result.get("ascii_plot")
    locations: list[dict[str, Any]] = [{"path": file_path}] if file_path else []

    content: list[dict[str, Any]] = []
    if ascii_plot:
        content = [
            {
                "type": "content",
                "content": {
                    "type": "text",
                    "text": f"```\n{ascii_plot}\n```",
                },
            }
        ]

    return ToolDisplay(
        title=title,
        kind=kind,
        content=content,
        locations=locations,
    )
