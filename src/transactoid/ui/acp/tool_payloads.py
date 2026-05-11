"""ACP rich tool call payload formatting.

Builds stable rawInput/rawOutput envelopes with versioned schemas.
Rendered content generation is handled by tool_presenter.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from transactoid.core.runtime.protocol import NamedOutput, ToolRuntimeInfo

SCHEMA_INPUT_V1 = "transactoid.tool_call.input.v1"
SCHEMA_OUTPUT_V1 = "transactoid.tool_call.output.v1"


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
