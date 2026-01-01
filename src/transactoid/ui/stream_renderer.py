from __future__ import annotations

from decimal import Decimal
import json
import sys
from typing import Any

from agents.items import (
    ItemHelpers,
    MessageOutputItem,
    ToolCallOutputItem,
)
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
)

# Color and streaming helpers


def _use_color() -> bool:
    """Check if terminal supports color output."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


COLORS = {
    "reason": "33",  # yellow
    "text": "37",  # white
    "tool": "36",  # cyan
    "args": "35",  # magenta
    "out": "34",  # blue
    "error": "31",  # red
    "faint": "90",
}


def colorize(text: str, key: str) -> str:
    """Apply ANSI color codes to text if terminal supports it."""
    if not _use_color():
        return text
    code = COLORS.get(key, "0")
    return f"\033[{code}m{text}\033[0m"


class _JsonEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and other non-serializable types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class ToolCallState:
    """Track state for a streaming tool call."""

    def __init__(self, call_id: str, name: str) -> None:
        self.call_id = call_id
        self.name = name
        self.args_chunks: list[str] = []

    def args_text(self) -> str:
        """Get accumulated arguments as a single string."""
        return "".join(self.args_chunks)


class StreamRenderer:
    """Handle rendering of streaming events to the console."""

    def __init__(self) -> None:
        self.tool_calls: dict[str, ToolCallState] = {}
        self._spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_index = 0
        self._thinking_shown = False

    def begin_turn(self, user_input: str) -> None:
        """Start a new turn with user input."""
        print("")
        self._show_thinking()

    def _show_thinking(self) -> None:
        """Display thinking indicator."""
        char = self._spinner_chars[self._spinner_index % len(self._spinner_chars)]
        print(f"\r{colorize(f'{char} Thinking...', 'faint')}", end="", flush=True)
        self._thinking_shown = True
        self._spinner_index += 1

    def _clear_thinking(self) -> None:
        """Clear the thinking indicator."""
        if self._thinking_shown:
            print("\r" + " " * 20 + "\r", end="", flush=True)
            self._thinking_shown = False

    def on_reasoning(self, delta: str) -> None:
        """Stream reasoning text in yellow."""
        self._clear_thinking()
        print(colorize(delta, "reason"), end="", flush=True)

    def on_output_text(self, delta: str) -> None:
        """Stream output text in white."""
        self._clear_thinking()
        print(colorize(delta, "text"), end="", flush=True)

    def on_tool_call_started(self, call_id: str, name: str) -> None:
        """Begin a new tool call."""
        self.tool_calls[call_id] = ToolCallState(call_id, name)

    def on_tool_arguments_delta(self, call_id: str, delta: str) -> None:
        """Accumulate tool call arguments (printed on completion)."""
        state = self.tool_calls.get(call_id)
        if not state:
            state = ToolCallState(call_id, "unknown")
            self.tool_calls[call_id] = state
        state.args_chunks.append(delta)

    def on_tool_call_completed(self, call_id: str) -> None:
        """Print tool call with pretty-printed arguments."""
        state = self.tool_calls.get(call_id)
        if not state:
            return
        self._clear_thinking()
        args_text = state.args_text()
        if not args_text:
            print(colorize(f"📞 {state.name}()", "tool"))
        else:
            try:
                args = json.loads(args_text)
                if state.name == "run_sql" and "query" in args:
                    query = args.pop("query")
                    args_str = json.dumps(args) if args else "{}"
                    print(colorize(f"📞 {state.name}({args_str})", "tool"))
                    print(colorize("SQL:", "args"))
                    print(colorize(query, "args"))
                else:
                    args_str = json.dumps(args)
                    print(colorize(f"📞 {state.name}({args_str})", "tool"))
            except json.JSONDecodeError:
                print(colorize(f"📞 {state.name}({args_text})", "tool"))
        print()

    def _summarize_tool_result(self, output: Any) -> tuple[str, str | None]:
        """Generate a brief summary of a tool result.

        Returns:
            Tuple of (summary_line, full_text_if_truncated_or_none)
        """
        if not isinstance(output, dict):
            text = str(output)
            if len(text) > 60:
                return (text[:60] + "...", text)
            return (text, None)

        parts = []
        full_error = None

        if "status" in output:
            parts.append(output["status"])
        if "error" in output:
            full_error = str(output["error"])
            # Short summary for the main line
            error_preview = full_error[:40] + "..." if len(full_error) > 40 else full_error
            parts.append(f"error: {error_preview}")
        if "accounts" in output:
            parts.append(f"{len(output['accounts'])} accounts")
        if "count" in output:
            parts.append(f"{output['count']} rows")
        if "total_added" in output:
            parts.append(f"+{output['total_added']} txns")
        if "message" in output and "status" not in output:
            msg = output["message"][:40]
            parts.append(msg)

        summary = ", ".join(parts) if parts else "{...}"
        return (summary, full_error)

    def on_tool_result(self, output: Any) -> None:
        """Display tool execution result in collapsed format with summary."""
        summary, full_text = self._summarize_tool_result(output)
        print(colorize(f"↩️ Tool result ▶ {summary}", "out"))

        # Print full text on separate lines if it was truncated
        if full_text:
            print(colorize("Full output:", "error"))
            print(colorize(full_text, "error"))

        print()

    def on_message_output(self, item: MessageOutputItem) -> None:
        """Display final message output if needed."""
        msg = ItemHelpers.text_message_output(item)
        if msg:
            print(colorize(msg, "text"))
            print()

    def on_unknown(self, _event: Any) -> None:
        """Handle unknown events safely."""
        pass

    def end_turn(self, result: Any | None) -> None:
        """Complete the turn and optionally show token usage."""
        self._clear_thinking()
        print()
        print()
        if result is not None:
            raw_responses = getattr(result, "raw_responses", None)
            if raw_responses:
                print("=== TOKEN USAGE ===")
                for raw in raw_responses:
                    usage = getattr(raw, "usage", None)
                    if usage:
                        print(usage)


class EventRouter:
    """Route SDK streaming events to appropriate renderer handlers."""

    def __init__(self, renderer: StreamRenderer) -> None:
        self.r = renderer
        # Track the latest call_id for SDKs that don't provide it on every args delta
        self._last_call_id: str | None = None

    def handle(self, event: Any) -> None:
        """Process a single streaming event."""
        et = getattr(event, "type", "")

        # Update spinner animation on each event while thinking
        if self.r._thinking_shown:
            self.r._show_thinking()

        # 1) Raw response events (reasoning, output text, function calls)
        if et == "raw_response_event":
            data = getattr(event, "data", None)
            if data is None:
                return

            dt = getattr(data, "type", "")

            # Reasoning summary text
            if dt == "response.reasoning_summary_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    self.r.on_reasoning(delta)
                return

            # Output text
            if dt == "response.output_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    self.r.on_output_text(delta)
                return

        # 2) Raw response sub-events for function calls
        if et == "raw_response_event":
            data = getattr(event, "data", None)
            if isinstance(data, ResponseFunctionCallArgumentsDeltaEvent):
                call_id = (
                    getattr(data, "call_id", None) or self._last_call_id or "unknown"
                )
                self.r.on_tool_arguments_delta(call_id, data.delta or "")
                return

            # Detect start/end of function call output items
            dt = getattr(data, "type", "")
            item = getattr(data, "item", None)

            if (
                dt == "response.output_item.added"
                and getattr(item, "type", "") == "function_call"
            ):
                name = getattr(item, "name", "unknown")
                call_id = getattr(item, "call_id", "unknown")
                self._last_call_id = call_id
                self.r.on_tool_call_started(call_id, name)
                return

            if dt == "response.output_item.done":
                call_id = getattr(item, "call_id", None)
                if call_id:
                    self.r.on_tool_call_completed(call_id)
                    if self._last_call_id == call_id:
                        self._last_call_id = None
                return

        # 3) Runner item events (tool call exec + outputs)
        if et == "run_item_stream_event":
            item = getattr(event, "item", None)
            # ToolCallOutputItem: the tool procedure finished and returned output
            if isinstance(item, ToolCallOutputItem):
                self.r.on_tool_result(item.output)
                return
            # MessageOutputItem: optional final assistant message object
            if isinstance(item, MessageOutputItem):
                # Only use if you're not already printing output_text.delta
                # self.r.on_message_output(item)
                return

        # Ignore cosmetic updates
        if et == "agent_updated_stream_event":
            return

        # Unknown/unhandled
        self.r.on_unknown(event)
