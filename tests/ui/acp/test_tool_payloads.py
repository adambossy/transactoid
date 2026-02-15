"""Tests for ACP tool payload formatting."""

from __future__ import annotations

from decimal import Decimal

from transactoid.core.runtime.protocol import NamedOutput, ToolRuntimeInfo
from transactoid.ui.acp.tool_payloads import (
    SCHEMA_INPUT_V1,
    SCHEMA_OUTPUT_V1,
    build_raw_input,
    build_raw_output,
    build_rendered_content_input,
    build_rendered_content_output,
)


def test_build_raw_input_minimal() -> None:
    """Test building raw input with minimal fields."""
    result = build_raw_input(
        tool_name="run_sql",
        arguments={"query": "SELECT * FROM transactions"},
    )

    expected = {
        "schema": SCHEMA_INPUT_V1,
        "tool": "run_sql",
        "arguments": {"query": "SELECT * FROM transactions"},
    }

    assert result == expected


def test_build_raw_input_with_runtime_info() -> None:
    """Test building raw input with runtime info."""
    runtime_info = ToolRuntimeInfo(
        command="sql",
        cwd="/app",
        exit_code=None,
        streams=None,
    )

    result = build_raw_input(
        tool_name="run_sql",
        arguments={"query": "SELECT 1"},
        runtime_info=runtime_info,
    )

    assert result["schema"] == SCHEMA_INPUT_V1
    assert result["tool"] == "run_sql"
    assert result["arguments"] == {"query": "SELECT 1"}
    assert result["runtime"] == {"command": "sql", "cwd": "/app"}


def test_build_raw_output_dict_result() -> None:
    """Test building raw output with dict result."""
    result = build_raw_output(
        status="completed",
        result={"rows": [{"id": 1}], "count": 1},
    )

    expected = {
        "schema": SCHEMA_OUTPUT_V1,
        "status": "completed",
        "result": {"rows": [{"id": 1}], "count": 1},
    }

    assert result == expected


def test_build_raw_output_string_result() -> None:
    """Test building raw output with string result."""
    result = build_raw_output(
        status="failed",
        result="Error: connection timeout",
    )

    expected = {
        "schema": SCHEMA_OUTPUT_V1,
        "status": "failed",
        "result": "Error: connection timeout",
    }

    assert result == expected


def test_build_raw_output_with_named_outputs() -> None:
    """Test building raw output with named outputs."""
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text="Query executed"),
        NamedOutput(name="stderr", mime_type="text/plain", text=""),
    ]

    result = build_raw_output(
        status="completed",
        result={"rows": [], "count": 0},
        named_outputs=named_outputs,
    )

    assert result["schema"] == SCHEMA_OUTPUT_V1
    assert result["status"] == "completed"
    assert len(result["namedOutputs"]) == 2
    assert result["namedOutputs"][0]["name"] == "stdout"
    assert result["namedOutputs"][0]["text"] == "Query executed"


def test_build_raw_output_with_runtime_info() -> None:
    """Test building raw output with runtime info."""
    runtime_info = ToolRuntimeInfo(
        command="sql",
        exit_code=0,
        streams={"stdout": "Success", "stderr": ""},
    )

    result = build_raw_output(
        status="completed",
        result={"success": True},
        runtime_info=runtime_info,
    )

    assert result["runtime"]["command"] == "sql"
    assert result["runtime"]["exitCode"] == 0
    assert result["runtime"]["streams"] == {"stdout": "Success", "stderr": ""}


def test_build_rendered_content_input_simple() -> None:
    """Test building rendered content for simple input."""
    content = build_rendered_content_input(
        tool_name="run_sql",
        arguments={"query": "SELECT 1"},
    )

    assert len(content) == 1
    assert content[0]["type"] == "content"
    assert "Arguments:" in content[0]["content"]["text"]
    assert "SELECT 1" in content[0]["content"]["text"]


def test_build_rendered_content_input_complex_args() -> None:
    """Test building rendered content for complex arguments."""
    content = build_rendered_content_input(
        tool_name="sync_transactions",
        arguments={"count": 250, "cursor": None, "force": False},
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "Arguments:" in text
    assert "250" in text


def test_build_rendered_content_output_dict_result() -> None:
    """Test building rendered content for dict result."""
    content = build_rendered_content_output(
        status="completed",
        result={"rows": [{"id": 1}], "count": 1},
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "rows" in text
    assert "```json" in text


def test_build_rendered_content_output_string_result() -> None:
    """Test building rendered content for string result."""
    content = build_rendered_content_output(
        status="failed",
        result="Connection timeout",
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "Connection timeout" in text


def test_build_rendered_content_output_with_named_outputs() -> None:
    """Test building rendered content with named outputs (shell command pattern)."""
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text="Synced 100 rows"),
    ]

    content = build_rendered_content_output(
        status="completed",
        result={"count": 100},
        named_outputs=named_outputs,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    # stdout is shown without label (shell command pattern)
    assert "Synced 100 rows" in text
    assert "stdout:" not in text
    # Result JSON is not shown when stdout is present
    assert "```json" not in text


def test_build_rendered_content_output_with_non_stdout_named_outputs() -> None:
    """Test building rendered content with non-stdout named outputs."""
    named_outputs = [
        NamedOutput(name="result", mime_type="application/json", text='{"count": 100}'),
        NamedOutput(name="metadata", mime_type="text/plain", text="Extra info"),
    ]

    content = build_rendered_content_output(
        status="completed",
        result={"count": 100},
        named_outputs=named_outputs,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    # Non-stdout outputs are shown with labels
    assert "result:" in text
    assert "metadata:" in text
    assert "Extra info" in text


def test_runtime_info_serialization_omits_none_fields() -> None:
    """Test that runtime info serialization omits None fields."""
    runtime_info = ToolRuntimeInfo(
        command="test",
        cwd=None,
        exit_code=None,
        streams=None,
    )

    result = build_raw_output(
        status="completed",
        result={"test": True},
        runtime_info=runtime_info,
    )

    assert "runtime" in result
    assert "command" in result["runtime"]
    assert "cwd" not in result["runtime"]
    assert "exitCode" not in result["runtime"]
    assert "streams" not in result["runtime"]


def test_build_rendered_content_output_with_decimal_values() -> None:
    """Test that Decimal values are properly serialized in rendered content."""
    result_with_decimal = {
        "rows": [
            {"id": 1, "amount": Decimal("123.45")},
            {"id": 2, "amount": Decimal("678.90")},
        ],
        "count": 2,
    }

    content = build_rendered_content_output(
        status="completed",
        result=result_with_decimal,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "```json" in text
    assert "123.45" in text
    assert "678.9" in text or "678.90" in text
    assert "Decimal" not in text


def test_build_rendered_content_input_with_decimal_in_args() -> None:
    """Test that Decimal values in arguments are properly serialized."""
    arguments = {
        "min_amount": Decimal("100.00"),
        "max_amount": Decimal("500.50"),
    }

    content = build_rendered_content_input(
        tool_name="filter_transactions",
        arguments=arguments,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "100.0" in text or "100.00" in text
    assert "500.5" in text or "500.50" in text
    assert "Decimal" not in text


def test_build_rendered_content_input_with_shell_command() -> None:
    """Test shell command pattern - command shown instead of JSON args."""
    runtime_info = ToolRuntimeInfo(
        command='find . -type f -name "*.html"',
        cwd="/app",
    )

    content = build_rendered_content_input(
        tool_name="execute_shell",
        arguments={"command": 'find . -type f -name "*.html"'},
        runtime_info=runtime_info,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    # Command is shown as header
    assert 'find . -type f -name "*.html"' in text
    # Arguments JSON is not shown
    assert "Arguments:" not in text
    assert "```json" not in text


def test_build_rendered_content_output_with_shell_stdout() -> None:
    """Test shell command output pattern - stdout shown without label."""
    stdout_text = "./index.html\n./about.html"
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text=stdout_text),
        NamedOutput(name="stderr", mime_type="text/plain", text=""),
    ]

    content = build_rendered_content_output(
        status="completed",
        result={"exit_code": 0},
        named_outputs=named_outputs,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    # stdout shown without label
    assert "./index.html" in text
    assert "./about.html" in text
    assert "stdout:" not in text
    # Empty stderr not shown
    assert "stderr:" not in text
    # Result JSON not shown when stdout present
    assert "exit_code" not in text


def test_build_rendered_content_output_with_shell_stderr() -> None:
    """Test shell command with stderr - both stdout and stderr shown."""
    stderr_text = "Warning: file not found"
    named_outputs = [
        NamedOutput(name="stdout", mime_type="text/plain", text="Processing..."),
        NamedOutput(name="stderr", mime_type="text/plain", text=stderr_text),
    ]

    content = build_rendered_content_output(
        status="completed",
        result={"exit_code": 0},
        named_outputs=named_outputs,
    )

    assert len(content) == 1
    text = content[0]["content"]["text"]
    assert "Processing..." in text
    assert "stderr:" in text
    assert "Warning: file not found" in text
