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

Text/reasoning segmenting: a provider streams one assistant turn as many model
steps, and some providers reuse a single ``message_id`` for every step (Gemini
hardcodes ``"gemini-msg"``). So text is *not* keyed by ``message_id`` — that
would merge text from different steps (e.g. a mid-turn note and the final answer)
into one part pinned at the earliest step, printing the answer *above* the tool
calls that produced it. Instead each contiguous text (or reasoning) run is its
own uniquely-keyed part, opened lazily on the first real delta and closed at the
next step/tool boundary, so parts land in true transcript order.
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
        # Text/reasoning segmenting: a monotonic counter mints a unique key per
        # contiguous run; the ``_open_*`` keys name the run currently accepting
        # deltas (``None`` once a step/tool boundary has closed it).
        self._segment_counter: int = 0
        self._open_text_key: str | None = None
        self._open_reasoning_key: str | None = None

    # ----- ingestion -------------------------------------------------------

    def consume(self, event: Any) -> None:
        """Fold one harness event into the accumulating parts."""
        if isinstance(event, RunStart):
            self.run_id = event.run_id
        elif isinstance(event, ThinkingStart):
            # A new reasoning run begins; any open text run is complete.
            self._open_text_key = None
            self._open_reasoning_key = None
        elif isinstance(event, ThinkingDelta):
            part = self._open_reasoning()
            part["text"] += event.delta
        elif isinstance(event, ThinkingEnd):
            self._open_reasoning_key = None
        elif isinstance(event, MessageDelta):
            part = self._open_text()
            part["text"] += event.delta
        elif isinstance(event, MessageEnd):
            # Step boundary: close the runs so the next step's text/reasoning
            # opens a fresh part in transcript order (message_id is not unique).
            self._open_text_key = None
            self._open_reasoning_key = None
        elif isinstance(event, ToolCallEnd):
            # A tool call interrupts any open text/reasoning run.
            self._open_text_key = None
            self._open_reasoning_key = None
            self._add_tool_call(event)
        elif isinstance(event, ToolExecEnd):
            self._promote_tool_result(event)
        elif isinstance(event, Error):
            self._open_text_key = None
            self._open_reasoning_key = None
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

    def _open_reasoning(self) -> dict[str, Any]:
        """Return the open reasoning run, opening a new one at the current
        position if none is active."""
        if self._open_reasoning_key is None:
            self._segment_counter += 1
            key = f"r_{self._segment_counter}"
            self._parts[key] = {"type": "reasoning", "text": "", "state": "done"}
            self._order.append(key)
            self._open_reasoning_key = key
        return self._parts[self._open_reasoning_key]

    def _open_text(self) -> dict[str, Any]:
        """Return the open text run, opening a new one at the current position
        if none is active."""
        if self._open_text_key is None:
            self._segment_counter += 1
            key = f"t_{self._segment_counter}"
            self._parts[key] = {"type": "text", "text": "", "state": "done"}
            self._order.append(key)
            self._open_text_key = key
        return self._parts[self._open_text_key]

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
