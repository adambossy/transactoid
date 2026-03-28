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
    ToolCallInputEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
)
from transactoid.services.agent_run.state import (
    ContinuationState,
    ConversationTurn,
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
        self.captured_input_texts: list[str] = []

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
        self.captured_input_texts.append(input_text)
        _ = session
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

    def test_handle_prompt_does_not_overwrite_tool_title_with_empty_input_title(
        self,
    ) -> None:
        class _CapturingNotifier:
            def __init__(self) -> None:
                self.tool_call_updates: list[dict[str, Any]] = []

            async def tool_call(
                self,
                session_id: str,
                tool_call_id: str,
                title: str,
                kind: str,
                status: str,
                raw_input: dict[str, Any] | None = None,
                content: list[dict[str, Any]] | None = None,
                locations: list[dict[str, Any]] | None = None,
            ) -> None:
                _ = (
                    session_id,
                    tool_call_id,
                    title,
                    kind,
                    status,
                    raw_input,
                    content,
                    locations,
                )

            async def tool_call_update(
                self,
                session_id: str,
                tool_call_id: str,
                status: str,
                content: list[dict[str, Any]] | None = None,
                raw_output: dict[str, Any] | None = None,
                title: str | None = None,
                kind: str | None = None,
                locations: list[dict[str, Any]] | None = None,
            ) -> None:
                _ = session_id
                self.tool_call_updates.append(
                    {
                        "tool_call_id": tool_call_id,
                        "status": status,
                        "title": title,
                        "kind": kind,
                        "content": content,
                        "raw_output": raw_output,
                        "locations": locations,
                    }
                )

            async def agent_message_chunk(
                self, session_id: str, content: dict[str, Any]
            ) -> None:
                _ = (session_id, content)

            async def agent_thought_chunk(
                self, session_id: str, content: dict[str, Any]
            ) -> None:
                _ = (session_id, content)

        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "Show yesterday's transactions"}],
        }
        runtime_events = [
            ToolCallStartedEvent(
                call_id="call_sql",
                tool_name="run_sql",
                kind="execute",
            ),
            ToolCallInputEvent(
                call_id="call_sql",
                tool_name="run_sql",
                arguments={},
                runtime_info=None,
            ),
            ToolCallCompletedEvent(call_id="call_sql"),
            ToolOutputEvent(call_id="call_sql", output={"rows": [], "count": 0}),
            TurnCompletedEvent(final_text="Done"),
        ]
        notifier = _CapturingNotifier()

        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=runtime_events),
            notifier=notifier,  # type: ignore[arg-type]
        )

        output = _run_async(handler.handle_prompt(input_data))

        expected_output = {"stopReason": "end_turn"}

        assert output == expected_output
        pending_update = next(
            update
            for update in notifier.tool_call_updates
            if update["tool_call_id"] == "call_sql" and update["status"] == "pending"
        )
        assert pending_update["title"] is None


class TestPromptHandlerResume:
    """Tests for prior-turn injection on resumed sessions."""

    def test_prompt_prepends_prior_turns_on_resumed_session(self) -> None:
        # input
        continuation_state = ContinuationState(
            run_id="abc123",
            turns=[
                ConversationTurn(role="user", content="Generate report"),
                ConversationTurn(role="assistant", content="Here is the report."),
            ],
        )

        # setup
        session_manager = SessionManager()
        session_id = session_manager.create_with_continuation(
            cwd="/home/user",
            mcp_servers=[],
            continuation_state=continuation_state,
        )
        runtime = _FakeRuntime()
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=runtime,
            notifier=UpdateNotifier(StdioTransport()),
        )
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "Tell me more"}],
        }

        # act
        _run_async(handler.handle_prompt(input_data))

        # expected
        expected_input = (
            '<prior_turn role="user">Generate report</prior_turn>\n'
            '<prior_turn role="assistant">Here is the report.</prior_turn>\n'
            "<current_prompt>\nTell me more\n</current_prompt>"
        )

        # assert
        assert len(runtime.captured_input_texts) == 1
        assert runtime.captured_input_texts[0] == expected_input

    def test_prompt_clears_continuation_after_first_prompt(self) -> None:
        # input
        continuation_state = ContinuationState(
            run_id="abc123",
            turns=[
                ConversationTurn(role="user", content="Generate report"),
                ConversationTurn(role="assistant", content="Here is the report."),
            ],
        )

        # setup
        session_manager = SessionManager()
        session_id = session_manager.create_with_continuation(
            cwd="/home/user",
            mcp_servers=[],
            continuation_state=continuation_state,
        )
        runtime = _FakeRuntime()
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=runtime,
            notifier=UpdateNotifier(StdioTransport()),
        )

        # act — first prompt consumes continuation state
        _run_async(
            handler.handle_prompt(
                {
                    "sessionId": session_id,
                    "content": [{"type": "text", "text": "Tell me more"}],
                }
            )
        )
        # act — second prompt should be plain
        _run_async(
            handler.handle_prompt(
                {
                    "sessionId": session_id,
                    "content": [{"type": "text", "text": "Thanks"}],
                }
            )
        )

        # assert
        session = session_manager.get(session_id)
        assert session is not None
        assert session.continuation_state is None
        assert len(runtime.captured_input_texts) == 2
        # Second prompt should be raw text, no prior_turn blocks
        assert "<prior_turn" not in runtime.captured_input_texts[1]
        assert runtime.captured_input_texts[1] == "Thanks"
