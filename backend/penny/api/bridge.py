"""Translate agent-harness events into the Vercel AI SDK UI message stream.

The frontend (``@adambossy/agent-ui`` via the AI SDK ``useChat``) consumes an
SSE stream of JSON frames tagged ``x-vercel-ai-ui-message-stream: v1``. The
harness instead publishes a typed ``Event`` union on an ``EventBus``. This
module subscribes to the bus, runs the agent, and maps each event to the
corresponding stream frame(s).

Frame sequence per turn:
    start -> start-step -> (reasoning-* | text-* | tool-input/-output)* ->
    finish-step -> finish -> [DONE]
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from agent_harness import Agent
from agent_harness.core.events import (
    Error,
    InMemoryEventBus,
    MessageDelta,
    MessageEnd,
    MessageStart,
    RunEnd,
    RunStart,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolCallEnd,
    ToolExecEnd,
)


def _sse(frame: dict[str, Any]) -> str:
    return f"data: {json.dumps(frame)}\n\n"


def _serialize_tool_output(result: Any) -> dict[str, Any]:
    text_parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            text_parts.append(text)
    out: dict[str, Any] = {"text": "".join(text_parts)}
    error = getattr(result, "error", None)
    if error:
        out["error"] = error
    return out


def _translate(event: Any, open_text: set[str]) -> list[dict[str, Any]]:
    """Map one harness event to zero or more AI SDK stream frames.

    ``open_text`` tracks which text parts have emitted a ``text-start`` so a
    tool-only assistant message (no text deltas) never opens an empty bubble.
    """
    if isinstance(event, RunStart):
        return [{"type": "start", "messageId": event.run_id}, {"type": "start-step"}]
    if isinstance(event, ThinkingStart):
        return [{"type": "reasoning-start", "id": f"r_{event.message_id}"}]
    if isinstance(event, ThinkingDelta):
        return [{"type": "reasoning-delta", "id": f"r_{event.message_id}", "delta": event.delta}]
    if isinstance(event, ThinkingEnd):
        return [{"type": "reasoning-end", "id": f"r_{event.message_id}"}]
    if isinstance(event, MessageStart):
        return []  # text part opens lazily on the first delta
    if isinstance(event, MessageDelta):
        text_id = f"t_{event.message_id}"
        frames: list[dict[str, Any]] = []
        if text_id not in open_text:
            open_text.add(text_id)
            frames.append({"type": "text-start", "id": text_id})
        frames.append({"type": "text-delta", "id": text_id, "delta": event.delta})
        return frames
    if isinstance(event, MessageEnd):
        text_id = f"t_{event.message_id}"
        if text_id in open_text:
            open_text.discard(text_id)
            return [{"type": "text-end", "id": text_id}]
        return []
    if isinstance(event, ToolCallEnd):
        return [
            {
                "type": "tool-input-available",
                "toolCallId": event.tool_call_id,
                "toolName": event.tool_name,
                "input": event.arguments,
            }
        ]
    if isinstance(event, ToolExecEnd):
        return [
            {
                "type": "tool-output-available",
                "toolCallId": event.tool_call_id,
                "output": _serialize_tool_output(event.result),
            }
        ]
    if isinstance(event, RunEnd):
        return [{"type": "finish-step"}, {"type": "finish"}]
    if isinstance(event, Error):
        return [{"type": "error", "errorText": event.message}]
    return []


async def stream_agent(agent: Agent, prompt: str) -> AsyncIterator[str]:
    bus = InMemoryEventBus()
    subscription = bus.subscribe()

    async def _run() -> None:
        try:
            await agent.run(prompt=prompt, event_bus=bus)
        finally:
            await bus.close()

    runner = asyncio.create_task(_run())
    open_text: set[str] = set()
    try:
        async for event in subscription:
            for frame in _translate(event, open_text):
                yield _sse(frame)
    finally:
        try:
            await runner
        except Exception as exc:  # surface a loop failure to the client
            yield _sse({"type": "error", "errorText": str(exc)})
    yield "data: [DONE]\n\n"
