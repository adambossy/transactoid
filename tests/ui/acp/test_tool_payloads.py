"""Tests for ACP tool payload formatting."""

from __future__ import annotations

from transactoid.core.runtime.protocol import NamedOutput, ToolRuntimeInfo
from transactoid.ui.acp.tool_payloads import (
    SCHEMA_INPUT_V1,
    SCHEMA_OUTPUT_V1,
    build_raw_input,
    build_raw_output,
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
