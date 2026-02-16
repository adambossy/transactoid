"""Tests for ACP tool presenter."""

from __future__ import annotations

from decimal import Decimal

from transactoid.core.runtime.protocol import NamedOutput, ToolRuntimeInfo
from transactoid.ui.acp.tool_presenter import present_tool_input, present_tool_output


def test_present_run_sql_input() -> None:
    """Test run_sql input presentation with query truncation."""
    display = present_tool_input(
        tool_name="run_sql",
        arguments={"query": "SELECT * FROM transactions WHERE amount > 100"},
    )

    assert display.title == "SELECT * FROM transactions WHERE amount > 100"
    assert display.kind == "execute"
    assert len(display.content) == 1
    assert "```sql" in display.content[0]["content"]["text"]
    assert display.locations == []


def test_present_run_sql_input_long_query() -> None:
    """Test run_sql input with truncated long query."""
    long_query = (
        "SELECT * FROM transactions WHERE amount > 100 "
        "AND date > '2024-01-01' AND category = 'food'"
    )
    display = present_tool_input(
        tool_name="run_sql",
        arguments={"query": long_query},
    )

    assert len(display.title) <= 60
    assert display.title.endswith("...")
    assert display.kind == "execute"


def test_present_sync_transactions_input() -> None:
    """Test sync_transactions input presentation."""
    display = present_tool_input(
        tool_name="sync_transactions",
        arguments={"count": 250},
    )

    assert display.title == "Sync up to 250 transactions"
    assert display.kind == "fetch"
    assert display.content == []
    assert display.locations == []


def test_present_recategorize_merchant_input() -> None:
    """Test recategorize_merchant input presentation."""
    display = present_tool_input(
        tool_name="recategorize_merchant",
        arguments={
            "merchant_id": 123,
            "category_key": "food.groceries",
        },
    )

    assert display.title == "Recategorize merchant 123 → food.groceries"
    assert display.kind == "edit"
    assert display.content == []


def test_present_tag_transactions_input() -> None:
    """Test tag_transactions input presentation."""
    display = present_tool_input(
        tool_name="tag_transactions",
        arguments={
            "transaction_ids": [1, 2, 3],
            "tags": ["grocery", "food"],
        },
    )

    assert display.title == "Tag 3 transactions: grocery, food"
    assert display.kind == "edit"


def test_present_execute_shell_input() -> None:
    """Test execute_shell input with runtime info."""
    runtime_info = ToolRuntimeInfo(
        command="ls -la",
        cwd="/app",
    )

    display = present_tool_input(
        tool_name="execute_shell",
        arguments={"command": "ls -la"},
        runtime_info=runtime_info,
    )

    assert display.title == "`ls -la`"
    assert display.kind == "other"
    assert len(display.content) == 1
    assert display.content[0]["text"] == "ls -la"
    assert len(display.locations) == 1
    assert display.locations[0]["path"] == "/app"


def test_present_unknown_tool_input() -> None:
    """Test unknown tool fallback to JSON."""
    display = present_tool_input(
        tool_name="unknown_tool",
        arguments={"param1": "value1", "param2": 123},
    )

    assert display.title == "unknown_tool"
    assert display.kind == "other"
    assert len(display.content) == 1
    assert "```json" in display.content[0]["content"]["text"]
    assert "param1" in display.content[0]["content"]["text"]


def test_present_unknown_tool_input_with_decimal() -> None:
    """Test unknown tool fallback serializes Decimal values."""
    display = present_tool_input(
        tool_name="unknown_tool",
        arguments={"amount": Decimal("42.99")},
    )

    assert display.title == "unknown_tool"
    assert "42.99" in display.content[0]["content"]["text"]


def test_present_run_sql_output_success() -> None:
    """Test run_sql output presentation."""
    display = present_tool_output(
        tool_name="run_sql",
        arguments={"query": "SELECT 1"},
        status="completed",
        result={"rows": [{"result": 1}], "count": 1},
    )

    assert display.title == ""
    assert display.kind == "execute"
    assert len(display.content) == 1
    assert "```json" in display.content[0]["content"]["text"]
    assert "rows" in display.content[0]["content"]["text"]


def test_present_run_sql_output_failure() -> None:
    """Test run_sql output with error."""
    display = present_tool_output(
        tool_name="run_sql",
        arguments={"query": "INVALID SQL"},
        status="failed",
        result={"error": "syntax error near 'INVALID'"},
    )

    assert display.kind == "execute"
    assert "syntax error" in display.content[0]["content"]["text"]


def test_present_sync_transactions_output() -> None:
    """Test sync_transactions output summary."""
    display = present_tool_output(
        tool_name="sync_transactions",
        arguments={"count": 250},
        status="completed",
        result={"total_added": 10, "total_modified": 5, "total_removed": 2},
    )

    assert display.title == ""
    assert display.kind == "fetch"
    assert len(display.content) == 1
    assert "Added 10, modified 5, removed 2" in display.content[0]["text"]


def test_present_execute_shell_output() -> None:
    """Test execute_shell output with stdout/stderr."""
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text="file1.txt\nfile2.txt"),
        NamedOutput(name="stderr", mime_type="text/plain", text=""),
    ]

    display = present_tool_output(
        tool_name="execute_shell",
        arguments={"command": "ls"},
        status="completed",
        result={"exit_code": 0},
        named_outputs=named_outputs,
    )

    assert display.kind == "other"
    assert len(display.content) == 1
    assert "```sh" in display.content[0]["content"]["text"]
    assert "file1.txt" in display.content[0]["content"]["text"]
    assert (
        "stderr:" not in display.content[0]["content"]["text"]
    )  # Empty stderr not shown


def test_present_execute_shell_output_with_stderr() -> None:
    """Test execute_shell output with non-empty stderr."""
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text="output"),
        NamedOutput(name="stderr", mime_type="text/plain", text="warning: deprecated"),
    ]

    display = present_tool_output(
        tool_name="execute_shell",
        arguments={"command": "some-cmd"},
        status="completed",
        result={"exit_code": 0},
        named_outputs=named_outputs,
    )

    text = display.content[0]["content"]["text"]
    assert "output" in text
    assert "stderr:" in text
    assert "warning: deprecated" in text


def test_present_error_fallback() -> None:
    """Test generic error formatting."""
    display = present_tool_output(
        tool_name="any_tool",
        arguments={},
        status="failed",
        result="Connection timeout",
    )

    assert display.kind == "other"
    assert len(display.content) == 1
    assert "Connection timeout" in display.content[0]["content"]["text"]
    assert "```" in display.content[0]["content"]["text"]


def test_present_list_accounts_output_with_decimal() -> None:
    """Test list_accounts output serializes Decimal values."""
    display = present_tool_output(
        tool_name="list_accounts",
        arguments={},
        status="completed",
        result={"rows": [{"balance": Decimal("123.45")}]},
    )

    assert display.kind == "fetch"
    assert "123.45" in display.content[0]["content"]["text"]
