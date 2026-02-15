"""ACP rich tool call payload formatting.

Builds stable rawInput/rawOutput envelopes and rendered content blocks
that match the screenshot-like layout for tool execution display.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import json
from typing import Any

from transactoid.core.runtime.protocol import NamedOutput, ToolRuntimeInfo

SCHEMA_INPUT_V1 = "transactoid.tool_call.input.v1"
SCHEMA_OUTPUT_V1 = "transactoid.tool_call.output.v1"


class DatabaseJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles database types like Decimal, datetime, etc."""

    def default(self, obj: Any) -> Any:
        """Convert non-serializable types to serializable ones."""
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def build_raw_input(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
    runtime_info: ToolRuntimeInfo | None = None,
) -> dict[str, Any]:
    """Build stable rawInput envelope for tool call start.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments as dict
        runtime_info: Optional runtime metadata (command, cwd, etc.)

    Returns:
        rawInput envelope with schema version
    """
    envelope: dict[str, Any] = {
        "schema": SCHEMA_INPUT_V1,
        "tool": tool_name,
        "arguments": arguments,
    }
    if runtime_info is not None:
        envelope["runtime"] = _serialize_runtime_info(runtime_info)
    return envelope


def build_raw_output(
    *,
    status: str,
    result: dict[str, Any] | str,
    named_outputs: list[NamedOutput] | None = None,
    runtime_info: ToolRuntimeInfo | None = None,
) -> dict[str, Any]:
    """Build stable rawOutput envelope for tool call completion.

    Args:
        status: Tool execution status ("completed" or "failed")
        result: Tool result payload (dict or string)
        named_outputs: Optional list of named outputs (stdout, stderr, etc.)
        runtime_info: Optional runtime metadata (command, exit_code, etc.)

    Returns:
        rawOutput envelope with schema version
    """
    envelope: dict[str, Any] = {
        "schema": SCHEMA_OUTPUT_V1,
        "status": status,
        "result": result,
    }
    if named_outputs is not None:
        envelope["namedOutputs"] = [
            {
                "name": output.name,
                "mimeType": output.mime_type,
                "text": output.text,
            }
            for output in named_outputs
        ]
    if runtime_info is not None:
        envelope["runtime"] = _serialize_runtime_info(runtime_info)
    return envelope


def build_rendered_content_input(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
    runtime_info: ToolRuntimeInfo | None = None,
) -> list[dict[str, Any]]:
    """Build rendered content blocks for tool input.

    Args:
        tool_name: Name of the tool
        arguments: Tool arguments
        runtime_info: Optional runtime metadata (command, cwd, etc.)

    Returns:
        List of ACP content blocks
    """
    sections = []

    # If we have a shell command, show it as a header
    if runtime_info and runtime_info.command:
        sections.append(f"{runtime_info.command}\n\n")
    # Otherwise fall back to Arguments JSON
    elif arguments:
        args_json = json.dumps(arguments, indent=2, cls=DatabaseJSONEncoder)
        sections.append(f"Arguments:\n```json\n{args_json}\n```\n")

    combined_text = "".join(sections)
    return [{"type": "content", "content": {"type": "text", "text": combined_text}}]


def build_rendered_content_output(
    *,
    status: str,
    result: dict[str, Any] | str,
    named_outputs: list[NamedOutput] | None = None,
    runtime_info: ToolRuntimeInfo | None = None,
) -> list[dict[str, Any]]:
    """Build rendered content blocks for tool output.

    Args:
        status: Tool execution status
        result: Tool result payload
        named_outputs: Optional named outputs
        runtime_info: Optional runtime metadata (command, streams, etc.)

    Returns:
        List of ACP content blocks
    """
    sections = []

    # For shell commands, prefer stdout from named_outputs or streams
    stdout_found = False
    if named_outputs:
        stdout = next((o.text for o in named_outputs if o.name == "stdout"), None)
        if stdout:
            sections.append(stdout)
            stdout_found = True
            # Also include stderr if present and non-empty
            stderr = next((o.text for o in named_outputs if o.name == "stderr"), None)
            if stderr and stderr.strip():
                sections.append(f"\nstderr:\n{stderr}")
    elif runtime_info and runtime_info.streams:
        if "stdout" in runtime_info.streams:
            sections.append(runtime_info.streams["stdout"])
            stdout_found = True
        if "stderr" in runtime_info.streams and runtime_info.streams["stderr"].strip():
            sections.append(f"\nstderr:\n{runtime_info.streams['stderr']}")

    # If we found stdout, we're done (shell command output)
    if stdout_found:
        combined_text = "".join(sections)
        return [{"type": "content", "content": {"type": "text", "text": combined_text}}]

    # Otherwise, show other named outputs with labels
    if named_outputs:
        for output in named_outputs:
            if output.name not in ("stdout", "stderr"):
                sections.append(f"{output.name}:\n{output.text}\n\n")

    # Result content without label (for non-shell tools)
    if isinstance(result, dict):
        result_json = json.dumps(result, indent=2, cls=DatabaseJSONEncoder)
        sections.append(f"```json\n{result_json}\n```\n")
    elif isinstance(result, str):
        sections.append(f"{result}\n")

    combined_text = "".join(sections)
    return [{"type": "content", "content": {"type": "text", "text": combined_text}}]


def _serialize_runtime_info(info: ToolRuntimeInfo) -> dict[str, Any]:
    """Serialize ToolRuntimeInfo to dict, omitting None fields.

    Args:
        info: Runtime info to serialize

    Returns:
        Dict with only non-None fields
    """
    result: dict[str, Any] = {}
    if info.command is not None:
        result["command"] = info.command
    if info.cwd is not None:
        result["cwd"] = info.cwd
    if info.exit_code is not None:
        result["exitCode"] = info.exit_code
    if info.streams is not None:
        result["streams"] = info.streams
    return result
