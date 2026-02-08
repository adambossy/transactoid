"""Integration tests for ACP server full flow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import io
import json
from typing import Any
from unittest.mock import patch

from transactoid.core.runtime import (
    CoreRunResult,
    CoreSession,
    TextDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
)
from transactoid.ui.acp.handlers.initialize import handle_initialize
from transactoid.ui.acp.handlers.prompt import PromptHandler
from transactoid.ui.acp.handlers.session import SessionManager, handle_session_new
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.router import RequestRouter
from transactoid.ui.acp.transport import JsonRpcResponse, StdioTransport


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakeRuntime:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    def start_session(self, session_key: str) -> CoreSession:
        return CoreSession(session_id=session_key, native_session={"sid": session_key})

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


class TestACPServerFullFlow:
    def _create_session_manager(self) -> SessionManager:
        return SessionManager()

    def _create_router(self, session_manager: SessionManager) -> RequestRouter:
        router = RequestRouter()
        router.register("initialize", handle_initialize)

        async def session_new_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await handle_session_new(params, session_manager)

        router.register("session/new", session_new_handler)
        return router

    def test_full_flow_initialize_to_session_creation(self) -> None:
        session_manager = self._create_session_manager()
        router = self._create_router(session_manager)

        async def run_flow() -> tuple[dict[str, Any], dict[str, Any]]:
            init_result = await router.dispatch("initialize", {"protocolVersion": 1})
            session_result = await router.dispatch("session/new", {"cwd": "/home/user"})
            return init_result, session_result

        output = _run_async(run_flow())
        init_result, session_result = output

        assert init_result["protocolVersion"] == 1
        assert init_result["agentInfo"]["name"] == "transactoid"
        assert "agentCapabilities" in init_result
        assert "sessionId" in session_result

    def test_full_flow_with_prompt_and_updates(self) -> None:
        session_manager = self._create_session_manager()
        mock_stdout = io.StringIO()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        events = [
            TextDeltaEvent(text="Here's your balance..."),
            TextDeltaEvent(text=" $1,234.56"),
            TurnCompletedEvent(final_text="Here's your balance... $1,234.56"),
        ]
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=events),
            notifier=notifier,
        )

        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "What is my balance?"}],
        }

        with patch("sys.stdout", mock_stdout):
            result = _run_async(handler.handle_prompt(input_data))

        assert result == {"stopReason": "end_turn"}

        output = mock_stdout.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2

        notifications = [json.loads(line) for line in lines]
        assert (
            notifications[0]["params"]["update"]["content"]["text"]
            == "Here's your balance..."
        )
        assert notifications[1]["params"]["update"]["content"]["text"] == " $1,234.56"

    def test_full_flow_with_tool_call(self) -> None:
        session_manager = self._create_session_manager()
        mock_stdout = io.StringIO()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        events = [
            ToolCallStartedEvent(
                call_id="call_001", tool_name="run_sql", kind="execute"
            ),
            ToolCallCompletedEvent(call_id="call_001"),
            ToolOutputEvent(call_id="call_001", output="Query returned 15 rows"),
            TextDeltaEvent(text="I found 15 transactions."),
            TurnCompletedEvent(final_text="I found 15 transactions."),
        ]
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=events),
            notifier=notifier,
        )

        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        input_data = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "How many transactions?"}],
        }

        with patch("sys.stdout", mock_stdout):
            result = _run_async(handler.handle_prompt(input_data))

        assert result == {"stopReason": "end_turn"}

        output = mock_stdout.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 4


class TestACPServerTransportIntegration:
    def test_transport_roundtrip_with_router(self) -> None:
        session_manager = SessionManager()
        router = RequestRouter()
        router.register("initialize", handle_initialize)

        async def session_new_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await handle_session_new(params, session_manager)

        router.register("session/new", session_new_handler)

        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": 1},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": "/home/user"},
            },
        ]

        mock_stdin = io.StringIO(
            "\n".join(json.dumps(message) for message in messages) + "\n"
        )
        mock_stdout = io.StringIO()

        async def run_server() -> list[dict[str, Any]]:
            transport = StdioTransport()
            responses: list[dict[str, Any]] = []

            with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
                for _ in range(2):
                    request = await transport.read_message()
                    params = request.params or {}
                    result = await router.dispatch(request.method, params)
                    response = JsonRpcResponse(id=request.id, result=result)
                    await transport.write_response(response)
                    responses.append(result)

            return responses

        output = _run_async(run_server())

        assert output[0]["protocolVersion"] == 1
        assert output[1]["sessionId"].startswith("sess_")


class TestACPServerErrorHandling:
    def test_invalid_session_in_prompt_returns_error(self) -> None:
        session_manager = SessionManager()
        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=[]),
            notifier=UpdateNotifier(StdioTransport()),
        )

        input_data = {
            "sessionId": "sess_nonexistent",
            "content": [{"type": "text", "text": "Hello"}],
        }

        output = _run_async(handler.handle_prompt(input_data))

        assert output["error"]["code"] == -32600

    def test_empty_content_returns_error(self) -> None:
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])

        handler = PromptHandler(
            session_manager=session_manager,
            runtime=_FakeRuntime(events=[]),
            notifier=UpdateNotifier(StdioTransport()),
        )

        input_data = {
            "sessionId": session_id,
            "content": [],
        }

        output = _run_async(handler.handle_prompt(input_data))

        assert output["error"]["code"] == -32602


class TestACPServerMultiSession:
    def test_multiple_sessions_are_independent(self) -> None:
        session_manager = SessionManager()

        session1_id = session_manager.create(cwd="/home/user1", mcp_servers=[])
        session2_id = session_manager.create(cwd="/home/user2", mcp_servers=[])

        session_manager.add_message(
            session1_id, {"role": "user", "content": "Message 1"}
        )
        session_manager.add_message(
            session2_id, {"role": "user", "content": "Message 2"}
        )
        session_manager.add_message(
            session2_id, {"role": "user", "content": "Message 3"}
        )

        session1 = session_manager.get(session1_id)
        session2 = session_manager.get(session2_id)

        assert session1 is not None
        assert session2 is not None
        assert len(session1.messages) == 1
        assert len(session2.messages) == 2

    def test_version_negotiation_with_different_clients(self) -> None:
        async def run_negotiations() -> list[dict[str, Any]]:
            result1 = await handle_initialize({"protocolVersion": 1})
            result2 = await handle_initialize({"protocolVersion": 99})
            result3 = await handle_initialize({"protocolVersion": 0})
            return [result1, result2, result3]

        output = _run_async(run_negotiations())

        assert output[0]["protocolVersion"] == 1
        assert output[1]["protocolVersion"] == 1
        assert output[2]["protocolVersion"] == 0
