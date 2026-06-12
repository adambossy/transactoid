"""Accumulate harness events into a finalized AI SDK ``parts`` array.

This is the inverse of :func:`penny.api.bridge._translate`: where ``_translate``
maps one harness :class:`Event` to streaming frames for the browser, the
:class:`MessageAccumulator` folds the same event stream into the *final*
per-message ``parts`` array we persist (and later replay verbatim at
hydration). "What we persist" == "what we streamed" by construction.

Part shapes (mirroring ``_translate`` / what ``useChat`` expects):

- assistant text     -> ``{type: "text", text, state: "done"}``
- reasoning          -> ``{type: "reasoning", text, state: "done"}``
- tool call/result   -> ``{type: "tool-<name>", toolCallId, state, input, output}``
- tool error         -> ``{type: "tool-<name>", toolCallId, state: "output-error",
                           errorText, input}``
- stream-level error -> ``{type: "error", errorText}``

Ordering follows first-appearance of each part across the stream — exactly the
visual transcript order the bridge yields.
"""

from __future__ import annotations

from typing import Any

from agent_harness.core.events import (
    Error,
    MessageDelta,
    MessageEnd,
    RunEnd,
    RunStart,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    ToolCallEnd,
    ToolExecEnd,
)

from .bridge import _serialize_tool_output


class MessageAccumulator:
    """Folds one assistant turn's events into a finalized ``parts`` array.

    A single accumulator instance handles one ``RunStart``/``RunEnd`` turn. The
    ``run_id`` (== AI SDK ``messageId``) is captured on ``RunStart``.
    """

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.finished: bool = False
        self._saw_error: bool = False
        # Ordered part keys preserve first-appearance order.
        self._order: list[str] = []
        # key -> mutable part dict
        self._parts: dict[str, dict[str, Any]] = {}
        # tool_call_id -> part key (tool parts are keyed by call id)
        self._tool_keys: dict[str, str] = {}
        self._error_counter: int = 0

    # ----- ingestion -------------------------------------------------------

    def consume(self, event: Any) -> None:
        """Fold one harness event into the accumulating parts."""
        if isinstance(event, RunStart):
            self.run_id = event.run_id
        elif isinstance(event, ThinkingStart):
            self._ensure_reasoning(event.message_id)
        elif isinstance(event, ThinkingDelta):
            part = self._ensure_reasoning(event.message_id)
            part["text"] += event.delta
        elif isinstance(event, ThinkingEnd):
            self._ensure_reasoning(event.message_id)
        elif isinstance(event, MessageDelta):
            part = self._ensure_text(event.message_id)
            part["text"] += event.delta
        elif isinstance(event, MessageEnd):
            self._ensure_text(event.message_id)
        elif isinstance(event, ToolCallEnd):
            self._add_tool_call(event)
        elif isinstance(event, ToolExecEnd):
            self._promote_tool_result(event)
        elif isinstance(event, Error):
            self._add_stream_error(event.message)
        elif isinstance(event, RunEnd):
            self.finished = True

    # ----- finalized output ------------------------------------------------

    @property
    def status(self) -> str:
        """``complete`` on a clean finish, else ``error`` (incl. aborts)."""
        if self.finished and not self._saw_error:
            return "complete"
        return "error"

    def parts(self) -> list[dict[str, Any]]:
        """Return the finalized parts in first-appearance order.

        Empty text/reasoning parts are dropped (a tool-only turn never opens an
        empty text bubble), matching the bridge's lazy text-open behavior.
        """
        result: list[dict[str, Any]] = []
        for key in self._order:
            part = self._parts[key]
            if part["type"] in ("text", "reasoning") and not part.get("text"):
                continue
            result.append(part)
        return result

    # ----- internals -------------------------------------------------------

    def _ensure_reasoning(self, message_id: str) -> dict[str, Any]:
        key = f"r_{message_id}"
        part = self._parts.get(key)
        if part is None:
            part = {"type": "reasoning", "text": "", "state": "done"}
            self._parts[key] = part
            self._order.append(key)
        return part

    def _ensure_text(self, message_id: str) -> dict[str, Any]:
        key = f"t_{message_id}"
        part = self._parts.get(key)
        if part is None:
            part = {"type": "text", "text": "", "state": "done"}
            self._parts[key] = part
            self._order.append(key)
        return part

    def _add_tool_call(self, event: ToolCallEnd) -> None:
        key = f"tool_{event.tool_call_id}"
        part: dict[str, Any] = {
            "type": f"tool-{event.tool_name}",
            "toolCallId": event.tool_call_id,
            "state": "input-available",
            "input": event.arguments,
        }
        self._parts[key] = part
        self._tool_keys[event.tool_call_id] = key
        self._order.append(key)

    def _promote_tool_result(self, event: ToolExecEnd) -> None:
        key = self._tool_keys.get(event.tool_call_id)
        if key is None:
            # A result without a preceding call — synthesize a part so nothing
            # is silently dropped.
            key = f"tool_{event.tool_call_id}"
            self._parts[key] = {
                "type": "tool-unknown",
                "toolCallId": event.tool_call_id,
                "state": "input-available",
                "input": {},
            }
            self._tool_keys[event.tool_call_id] = key
            self._order.append(key)
        part = self._parts[key]

        result_error = getattr(event.result, "error", None)
        err_msg = event.error or result_error
        if err_msg:
            part["state"] = "output-error"
            part["errorText"] = str(err_msg)
            part.pop("output", None)
        else:
            part["state"] = "output-available"
            part["output"] = _serialize_tool_output(event.result)

    def _add_stream_error(self, message: str) -> None:
        self._saw_error = True
        key = f"err_{self._error_counter}"
        self._error_counter += 1
        self._parts[key] = {"type": "error", "errorText": message}
        self._order.append(key)
