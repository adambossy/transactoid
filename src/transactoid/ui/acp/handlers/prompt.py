"""Prompt processing handler for ACP protocol.

Handles 'session/prompt' requests by running the core runtime and streaming
responses back to the client via session/update notifications.
"""

from __future__ import annotations

from typing import Any

from transactoid.core.runtime import (
    CoreRuntime,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
)
from transactoid.ui.acp.handlers.session import SessionManager
from transactoid.ui.acp.logger import PromptHandlerLogger
from transactoid.ui.acp.notifier import UpdateNotifier


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

        async for event in self._runtime.run_streamed(
            input_text=user_text,
            session=runtime_session,
        ):
            event_count += 1
            self._log.event_received(event_count, type(event).__name__)
            maybe_final = await self._process_event(session_id=session_id, event=event)
            if maybe_final is not None:
                final_output = maybe_final

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
            self._log.tool_call_started(event.tool_name, event.call_id)
            await self._notifier.tool_call(
                session_id=session_id,
                tool_call_id=event.call_id,
                title=event.tool_name,
                kind=event.kind,
                status="pending",
            )
            return None

        if isinstance(event, ToolCallCompletedEvent):
            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.call_id,
                status="in_progress",
            )
            return None

        if isinstance(event, ToolOutputEvent):
            output_text = str(event.output)
            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.call_id,
                status="completed",
                content=[{"type": "text", "text": output_text}],
            )
            return None

        if isinstance(event, TurnCompletedEvent):
            return event.final_text

        self._log.unhandled_event(type(event).__name__)
        return None
