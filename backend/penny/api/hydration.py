"""Convert persisted harness messages into AI SDK ``UIMessage`` JSON.

Used by ``GET /api/sessions/{id}`` so the frontend can rehydrate a
conversation after a page refresh or backend restart. The mapping mirrors
what the live SSE stream produces:

- user text         -> ``{type: "text", text}``
- assistant text    -> ``{type: "text", text, state: "done"}``
- assistant tool    -> ``{type: "tool-<name>", toolCallId, state:
  "output-available", input, output}`` with the output joined from the
  matching ``ToolResultBlock`` in the subsequent tool-role message.
- assistant thinking -> ``{type: "reasoning", text, state: "done"}``
"""

from __future__ import annotations

import json
from typing import Any

from agent_harness.core.models import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)


def _parse_maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def _collect_tool_results(messages: list[Message]) -> dict[str, Any]:
    """Map tool_call_id -> parsed result content across all tool messages."""
    results: dict[str, Any] = {}
    for msg in messages:
        if msg.role != "tool":
            continue
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                content = block.content
                if isinstance(content, str):
                    results[block.tool_call_id] = _parse_maybe_json(content)
                else:
                    results[block.tool_call_id] = content
    return results


def messages_to_ui(messages: list[Message]) -> list[dict[str, Any]]:
    """Render harness session messages as AI SDK UIMessage dicts."""
    tool_results = _collect_tool_results(messages)
    ui_messages: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        if msg.role not in ("user", "assistant"):
            continue

        parts: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, ThinkingBlock):
                if not block.text:
                    continue
                parts.append({"type": "reasoning", "text": block.text, "state": "done"})
            elif isinstance(block, TextBlock):
                if not block.text:
                    continue
                part: dict[str, Any] = {"type": "text", "text": block.text}
                if msg.role == "assistant":
                    part["state"] = "done"
                parts.append(part)
            elif isinstance(block, ToolCallBlock):
                output = tool_results.get(block.id)
                parts.append(
                    {
                        "type": f"tool-{block.name}",
                        "toolCallId": block.id,
                        "state": "output-available"
                        if output is not None
                        else "input-available",
                        "input": block.arguments,
                        "output": output,
                    }
                )

        if parts:
            ui_messages.append({"id": f"hist_{idx}", "role": msg.role, "parts": parts})

    return ui_messages
