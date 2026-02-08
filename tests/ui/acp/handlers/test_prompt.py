"""Tests for ACP prompt handler."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from transactoid.core.runtime import (
    CoreRunResult,
    CoreSession,
    TextDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
)
from transactoid.ui.acp.handlers.prompt import PromptHandler
from transactoid.ui.acp.handlers.session import SessionManager
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.transport import StdioTransport


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakeRuntime:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or [TurnCompletedEvent(final_text="Test response")]

    def start_session(self, session_key: str) -> CoreSession:
        return CoreSession(session_id=session_key, native_session={"id": session_key})

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        _ = (input_text, session, max_turns)
        return CoreRunResult(final_text="", tool_calls=[], raw_metadata={})

    async def close(self) -> None:
        return None

    async def _stream(self) -> AsyncIterator[Any]:
        for event in self._events:
            yield event

    def run_streamed(
        self, *, input_text: str, session: CoreSession
    ) -> AsyncIterator[Any]:
        _ = (input_text, session)
        return self._stream()


class TestPromptHandlerValidation:
    def test_handle_prompt_returns_error_for_invalid_session(self) -> None:
        input_data = {
            "sessionId": "sess_invalid123",
            "content": [{"type": "text", "text": "Hello"}],
        }

        session_manager = SessionManager()
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(),
            notifier=UpdateNotifier(StdioTransport()),
        )

        output = _run_async(handler.handle_prompt(input_data))

        expected_output = {
            "error": {"code": -32600, "message": "Invalid session"},
        }

        assert output == expected_output

    def test_handle_prompt_returns_error_for_empty_content(self) -> None:
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [],
        }

        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(),
            notifier=UpdateNotifier(StdioTransport()),
        )

        output = _run_async(handler.handle_prompt(input_data))

        expected_output = {
            "error": {"code": -32602, "message": "No text content provided"},
        }

        assert output == expected_output


class TestPromptHandlerIntegration:
    def test_handle_prompt_returns_end_turn_on_success(self) -> None:
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "Hello"}],
        }

        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(),
            notifier=UpdateNotifier(StdioTransport()),
        )

        output = _run_async(handler.handle_prompt(input_data))

        expected_output = {"stopReason": "end_turn"}

        assert output == expected_output

    def test_handle_prompt_adds_assistant_message_and_emits_tool_updates(self) -> None:
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "How many transactions?"}],
        }
        runtime_events = [
            TextDeltaEvent(text="I will check that."),
            ToolCallStartedEvent(
                call_id="call_1",
                tool_name="run_sql",
                kind="execute",
            ),
            ToolCallCompletedEvent(call_id="call_1"),
            ToolOutputEvent(call_id="call_1", output={"rows": [], "count": 0}),
            TurnCompletedEvent(final_text="I found 0 transactions."),
        ]

        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=runtime_events),
            notifier=UpdateNotifier(StdioTransport()),
        )

        output = _run_async(handler.handle_prompt(input_data))
        session = session_manager.get(session_id)
        assert session is not None

        expected_output = {"stopReason": "end_turn"}

        assert output == expected_output
        assert session.messages[-1]["content"] == "I found 0 transactions."
