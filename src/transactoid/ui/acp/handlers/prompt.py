"""Prompt processing handler for ACP protocol.

Handles 'session/prompt' requests by running the core runtime and streaming
responses back to the client via session/update notifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from transactoid.core.runtime import (
    CoreRuntime,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallArgsDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallInputEvent,
    ToolCallOutputEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
)
from transactoid.ui.acp.handlers.session import SessionManager
from transactoid.ui.acp.logger import PromptHandlerLogger
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.tool_payloads import build_raw_output
from transactoid.ui.acp.tool_presenter import present_tool_input, present_tool_output


@dataclass
class ToolCallState:
    """Track state for a single tool call lifecycle."""

    call_id: str
    tool_name: str
    kind: str
    arguments: dict[str, object] = field(default_factory=dict)
    args_accumulated: str = ""
    status: str = "pending"
    output: dict[str, object] | str | None = None
    raw_input_sent: bool = False
    raw_output_sent: bool = False


class PromptHandler:
    """Handle session/prompt requests by running the provider-agnostic runtime."""

    def __init__(
        self,
        session_manager: SessionManager,
        runtime: CoreRuntime,
        notifier: UpdateNotifier,
    ) -> None:
        self._sessions = session_manager
        self._runtime = runtime
        self._notifier = notifier
        self._log = PromptHandlerLogger()
        self._runtime_sessions: dict[str, Any] = {}
        self._tool_states: dict[str, ToolCallState] = {}

    async def handle_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Process a user prompt and stream responses."""
        self._log.prompt_received(params.get("sessionId", ""), list(params.keys()))
        session_id = params.get("sessionId", "")
        content: list[dict[str, Any]] = (
            params.get("prompt") or params.get("content") or []
        )
        self._log.prompt_details(session_id, content)

        session = self._sessions.get(session_id)
        if session is None:
            self._log.invalid_session(session_id)
            return {"error": {"code": -32600, "message": "Invalid session"}}

        user_text = ""
        for block in content:
            if block.get("type") == "text":
                text_value = block.get("text")
                if isinstance(text_value, str):
                    user_text = text_value
                    break

        if not user_text:
            self._log.no_text_content()
            return {"error": {"code": -32602, "message": "No text content provided"}}

        self._log.user_prompt(session_id, user_text)
        self._sessions.add_message(session_id, {"role": "user", "content": user_text})

        if session_id not in self._runtime_sessions:
            self._runtime_sessions[session_id] = self._runtime.start_session(session_id)
        runtime_session = self._runtime_sessions[session_id]

        self._log.agent_stream_starting(session_id)
        event_count = 0
        final_output = ""
        self._tool_states.clear()

        async for event in self._runtime.run_streamed(
            input_text=user_text,
            session=runtime_session,
        ):
            event_count += 1
            self._log.event_received(event_count, type(event).__name__)
            maybe_final = await self._process_event(session_id=session_id, event=event)
            if maybe_final is not None:
                final_output = maybe_final

        await self._finalize_orphaned_calls(session_id)
        self._log.events_processed(session_id, event_count)

        if final_output:
            self._log.final_output(session_id, final_output)
            self._sessions.add_message(
                session_id,
                {"role": "assistant", "content": final_output},
            )

        self._log.returning_end_turn(session_id)
        return {"stopReason": "end_turn"}

    async def _process_event(self, session_id: str, event: Any) -> str | None:
        """Convert runtime stream events to ACP notifications."""
        if isinstance(event, TextDeltaEvent):
            await self._notifier.agent_message_chunk(
                session_id=session_id,
                content={"type": "text", "text": event.text},
            )
            return None

        if isinstance(event, ThoughtDeltaEvent):
            await self._notifier.agent_thought_chunk(
                session_id=session_id,
                content={"type": "thinking", "text": event.text},
            )
            return None

        if isinstance(event, ToolCallStartedEvent):
            await self._handle_tool_call_started(session_id, event)
            return None

        if isinstance(event, ToolCallArgsDeltaEvent):
            await self._handle_tool_args_delta(session_id, event)
            return None

        if isinstance(event, ToolCallInputEvent):
            await self._handle_tool_call_input(session_id, event)
            return None

        if isinstance(event, ToolCallCompletedEvent):
            await self._handle_tool_call_completed(session_id, event)
            return None

        if isinstance(event, ToolCallOutputEvent):
            await self._handle_tool_call_output(session_id, event)
            return None

        if isinstance(event, ToolOutputEvent):
            await self._handle_tool_output_legacy(session_id, event)
            return None

        if isinstance(event, TurnCompletedEvent):
            return event.final_text

        self._log.unhandled_event(type(event).__name__)
        return None

    async def _handle_tool_call_started(
        self, session_id: str, event: ToolCallStartedEvent
    ) -> None:
        """Handle tool call start: create state and send initial notification."""
        self._log.tool_call_started(event.tool_name, event.call_id)

        state = ToolCallState(
            call_id=event.call_id,
            tool_name=event.tool_name,
            kind=event.kind,
        )
        self._tool_states[event.call_id] = state

        await self._notifier.tool_call(
            session_id=session_id,
            tool_call_id=event.call_id,
            title=event.tool_name,
            kind=event.kind,
            status="pending",
        )

    async def _handle_tool_args_delta(
        self, session_id: str, event: ToolCallArgsDeltaEvent
    ) -> None:
        """Handle arguments delta: accumulate and try to parse."""
        state = self._tool_states.get(event.call_id)
        if state is None:
            state = ToolCallState(
                call_id=event.call_id,
                tool_name="unknown",
                kind="other",
            )
            self._tool_states[event.call_id] = state

        state.args_accumulated += event.delta

        try:
            parsed = json.loads(state.args_accumulated)
            if isinstance(parsed, dict):
                state.arguments = parsed
        except json.JSONDecodeError:
            pass

    async def _handle_tool_call_input(
        self, session_id: str, event: ToolCallInputEvent
    ) -> None:
        """Handle rich tool input event: send raw_input if not sent yet."""
        state = self._tool_states.get(event.call_id)
        if state is None:
            state = ToolCallState(
                call_id=event.call_id,
                tool_name=event.tool_name,
                kind="other",
            )
            self._tool_states[event.call_id] = state

        state.tool_name = event.tool_name
        state.arguments = event.arguments

        if not state.raw_input_sent:
            # Generate display payload for tool input
            display = present_tool_input(
                tool_name=event.tool_name,
                arguments=event.arguments,
                runtime_info=event.runtime_info,
            )

            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.call_id,
                status="pending",
                title=display.title,
                kind=display.kind,
                content=display.content,
                locations=display.locations if display.locations else None,
            )
            state.raw_input_sent = True

    async def _handle_tool_call_completed(
        self, session_id: str, event: ToolCallCompletedEvent
    ) -> None:
        """Handle tool call completion marker: transition to in_progress."""
        state = self._tool_states.get(event.call_id)
        if state is None:
            return

        state.status = "in_progress"

        if not state.raw_input_sent and state.arguments:
            display = present_tool_input(
                tool_name=state.tool_name,
                arguments=state.arguments,
                runtime_info=None,
            )
            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.call_id,
                status="in_progress",
                title=display.title,
                kind=display.kind,
                content=display.content,
                locations=display.locations if display.locations else None,
            )
            state.raw_input_sent = True
        else:
            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.call_id,
                status="in_progress",
            )

    async def _handle_tool_call_output(
        self, session_id: str, event: ToolCallOutputEvent
    ) -> None:
        """Handle rich tool output event: send final update with raw_output."""
        state = self._tool_states.get(event.call_id)
        if state is None:
            state = ToolCallState(
                call_id=event.call_id,
                tool_name="unknown",
                kind="other",
            )
            self._tool_states[event.call_id] = state

        state.output = event.output
        state.status = event.status

        raw_output = build_raw_output(
            status=event.status,
            result=event.output,
            named_outputs=event.named_outputs,
            runtime_info=event.runtime_info,
        )

        # Generate display payload for tool output
        # Need to handle case where output could be string or dict
        result_dict: dict[str, object] | str
        if isinstance(event.output, dict):
            result_dict = event.output
        else:
            result_dict = str(event.output)

        display = present_tool_output(
            tool_name=state.tool_name,
            arguments=state.arguments,
            status=event.status,
            result=result_dict,
            named_outputs=event.named_outputs,
            runtime_info=event.runtime_info,
        )

        await self._notifier.tool_call_update(
            session_id=session_id,
            tool_call_id=event.call_id,
            status=event.status,
            raw_output=raw_output,
            content=display.content,
            locations=display.locations if display.locations else None,
        )
        state.raw_output_sent = True

    async def _handle_tool_output_legacy(
        self, session_id: str, event: ToolOutputEvent
    ) -> None:
        """Handle legacy tool output event: fallback for simple outputs."""
        state = self._tool_states.get(event.call_id)
        if state is None:
            return

        if state.raw_output_sent:
            return

        state.output = event.output
        state.status = "completed"

        raw_output = build_raw_output(
            status="completed",
            result=event.output,
            named_outputs=None,
            runtime_info=None,
        )

        # Generate display payload for tool output
        result_dict: dict[str, object] | str
        if isinstance(event.output, dict):
            result_dict = event.output
        else:
            result_dict = str(event.output)

        display = present_tool_output(
            tool_name=state.tool_name,
            arguments=state.arguments,
            status="completed",
            result=result_dict,
            named_outputs=None,
            runtime_info=None,
        )

        await self._notifier.tool_call_update(
            session_id=session_id,
            tool_call_id=event.call_id,
            status="completed",
            raw_output=raw_output,
            content=display.content,
            locations=display.locations if display.locations else None,
        )
        state.raw_output_sent = True

    async def _finalize_orphaned_calls(self, session_id: str) -> None:
        """Send failed updates for any tool calls that didn't complete."""
        for call_id, state in self._tool_states.items():
            if not state.raw_output_sent:
                self._log.orphaned_tool_call(call_id, state.tool_name)
                await self._notifier.tool_call_update(
                    session_id=session_id,
                    tool_call_id=call_id,
                    status="failed",
                    content=[
                        {
                            "type": "text",
                            "text": "Tool call did not complete (timeout or error)",
                        }
                    ],
                )
