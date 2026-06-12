"""Reverse-map stored conversation ``parts`` → harness ``Message``s.

This is the inverse of both ``bridge.py::_translate`` / ``MessageAccumulator``
(it consumes the UI ``parts`` they produced) **and** of the harness ``Message``
serialization (its output is what the loop feeds the model). It exists so that,
with ``Agent(persist_session=False)`` (no ``sessions.db`` writes), each
``POST /api/chat`` can seed the agent with prior-turn context reconstructed from
the **app store** — making the model *see* the earlier conversation, not merely
re-render it in the UI.

It imports only ``agent_harness.core.models`` (a model-boundary type, not an
agent tool/skill), so it stays within the website domain per the segregation
rule.

Mapping (per stored message row, in ``seq`` order):

- user row            -> one ``Message(role="user", [TextBlock])``
- assistant row       -> a ``Message(role="assistant", ...)`` carrying
  ``ThinkingBlock`` / ``TextBlock`` / ``ToolCallBlock``, **paired** with a
  trailing ``Message(role="tool", ...)`` carrying the matching
  ``ToolResultBlock``s — the harness's two-message tool round-trip shape.
- stream ``error`` parts are dropped (a UI artifact, not model content).

Tool name is recovered by stripping the ``tool-`` prefix from the part ``type``.
A tool ``output-error`` maps to a model-visible ``ToolResultBlock`` whose content
is ``"Error: <errorText>"`` so the model sees the failure rather than a gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any

from agent_harness.core.models import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)

if TYPE_CHECKING:
    from .models import ConversationMessage

# A fixed timestamp for reconstructed messages — the original wall-clock time is
# not load-bearing for model continuity, and the harness only needs *a*
# timestamp on each Message.
_SEED_TS = datetime(1970, 1, 1, tzinfo=UTC)


def _output_to_text(output: Any) -> str:
    """Render a stored tool ``output`` to the text the model should see."""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


def _row_text(parts: list[dict[str, Any]]) -> str:
    return "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _assistant_messages(parts: list[dict[str, Any]]) -> list[Message]:
    """Build the assistant message (+ optional trailing tool message)."""
    content: list[Any] = []
    tool_results: list[ToolResultBlock] = []

    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "reasoning":
            text = str(part.get("text", ""))
            if text:
                content.append(ThinkingBlock(text=text))
        elif part_type == "text":
            text = str(part.get("text", ""))
            if text:
                content.append(TextBlock(text=text))
        elif part_type == "error":
            # Stream-level error: a UI banner, not model-visible content.
            continue
        elif isinstance(part_type, str) and part_type.startswith("tool-"):
            tool_name = part_type[len("tool-") :]
            tool_call_id = str(part.get("toolCallId", ""))
            arguments = part.get("input") or {}
            content.append(
                ToolCallBlock(
                    id=tool_call_id,
                    name=tool_name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
            state = part.get("state")
            if state == "output-error":
                tool_results.append(
                    ToolResultBlock(
                        tool_call_id=tool_call_id,
                        content=f"Error: {part.get('errorText', '')}",
                    )
                )
            elif "output" in part:
                tool_results.append(
                    ToolResultBlock(
                        tool_call_id=tool_call_id,
                        content=_output_to_text(part.get("output")),
                    )
                )

    messages: list[Message] = []
    if content:
        messages.append(Message(role="assistant", content=content, timestamp=_SEED_TS))
    if tool_results:
        messages.append(
            Message(role="tool", content=list(tool_results), timestamp=_SEED_TS)
        )
    return messages


def parts_to_messages(rows: list[ConversationMessage]) -> list[Message]:
    """Reverse-map stored conversation rows to harness ``Message``s.

    Returns the messages in ``seq`` order (rows are expected pre-sorted by
    ``get_conversation_messages``). Only ``complete`` user/assistant content is
    reconstructed; the system prompt is added by the loop, not seeded here.
    """
    messages: list[Message] = []
    for row in rows:
        parts = row.parts or []
        if row.role == "user":
            text = _row_text(parts)
            messages.append(
                Message(role="user", content=[TextBlock(text=text)], timestamp=_SEED_TS)
            )
        elif row.role == "assistant":
            messages.extend(_assistant_messages(parts))
    return messages
