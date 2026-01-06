"""Integration tests for ACP server full flow.

Tests the complete ACP server workflow: initialize → session/new → session/prompt
with proper routing and notification streaming.
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from transactoid.ui.acp.handlers.initialize import handle_initialize
from transactoid.ui.acp.handlers.prompt import PromptHandler
from transactoid.ui.acp.handlers.session import SessionManager, handle_session_new
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.router import RequestRouter
from transactoid.ui.acp.transport import (
    JsonRpcResponse,
    StdioTransport,
)


def _run_async(coro: Any) -> Any:
    """Run an async function synchronously."""
    return asyncio.run(coro)


class TestACPServerFullFlow:
    """Integration tests for full ACP server flow."""

    @pytest.fixture
    def session_manager(self) -> SessionManager:
        """Create a fresh SessionManager for each test."""
        return SessionManager()

    @pytest.fixture
    def router(self, session_manager: SessionManager) -> RequestRouter:
        """Create a router with all handlers registered."""
        router = RequestRouter()

        # Register initialize handler
        router.register("initialize", handle_initialize)

        # Register session/new handler with session manager bound
        async def session_new_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await handle_session_new(params, session_manager)

        router.register("session/new", session_new_handler)

        return router

    def test_full_flow_initialize_to_session_creation(
        self,
        router: RequestRouter,
        session_manager: SessionManager,
    ) -> None:
        """Test initialize → session/new flow through router."""

        async def run_flow() -> tuple[dict[str, Any], dict[str, Any]]:
            # Step 1: Initialize
            init_result = await router.dispatch("initialize", {"protocolVersion": 1})

            # Step 2: Create session
            session_result = await router.dispatch("session/new", {"cwd": "/home/user"})

            return init_result, session_result

        init_result, session_result = _run_async(run_flow())

        # Verify initialize response
        assert init_result["protocolVersion"] == 1
        assert init_result["agentInfo"]["name"] == "transactoid"
        assert "agentCapabilities" in init_result

        # Verify session creation
        assert "sessionId" in session_result
        session_id = session_result["sessionId"]
        assert session_id.startswith("sess_")

        # Verify session exists in manager
        session = session_manager.get(session_id)
        assert session is not None
        assert session.cwd == "/home/user"

    def test_full_flow_with_prompt_and_updates(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Test full flow: init → new → prompt with streaming updates."""
        mock_stdout = io.StringIO()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        # Create mock agent and stream
        mock_agent = MagicMock()
        mock_stream = MagicMock()

        # Create streaming events that simulate agent behavior
        async def mock_stream_events() -> Any:
            # Simulate a message delta event
            event1 = MagicMock()
            event1.type = "raw_response_event"
            event1.data = MagicMock()
            event1.data.type = "response.output_text.delta"
            event1.data.delta = "Here's your balance..."
            yield event1

            # Simulate another delta
            event2 = MagicMock()
            event2.type = "raw_response_event"
            event2.data = MagicMock()
            event2.data.type = "response.output_text.delta"
            event2.data.delta = " $1,234.56"
            yield event2

        mock_stream.stream_events = mock_stream_events

        # Mock get_final_result
        final_result = MagicMock()
        final_result.final_output = "Here's your balance... $1,234.56"
        mock_stream.get_final_result = MagicMock(return_value=final_result)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=mock_agent,
            notifier=notifier,
        )

        # Create a session first
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "What is my balance?"}],
        }

        async def run_prompt() -> dict[str, Any]:
            with (
                patch("transactoid.ui.acp.handlers.prompt.Runner") as mock_runner,
                patch("transactoid.ui.acp.handlers.prompt.SQLiteSession"),
            ):
                mock_runner.run_streamed.return_value = mock_stream
                return await handler.handle_prompt(params)

        with patch("sys.stdout", mock_stdout):
            result = _run_async(run_prompt())

        # Verify result
        assert result == {"stopReason": "end_turn"}

        # Verify notifications were sent
        output = mock_stdout.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2  # Two message deltas

        notifications = [json.loads(line) for line in lines]

        # Both should be agent_message_chunk notifications
        for notification in notifications:
            assert notification["method"] == "session/update"
            update_type = "agent_message_chunk"
            assert notification["params"]["update"]["sessionUpdate"] == update_type

        # Check content of deltas (now single objects, not lists)
        assert notifications[0]["params"]["update"]["content"] == {
            "type": "text",
            "text": "Here's your balance...",
        }
        assert notifications[1]["params"]["update"]["content"] == {
            "type": "text",
            "text": " $1,234.56",
        }

        # Verify message was added to session history
        session = session_manager.get(session_id)
        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "What is my balance?"
        assert session.messages[1]["role"] == "assistant"

    def test_full_flow_with_tool_call(
        self,
        session_manager: SessionManager,
    ) -> None:
        """Test full flow with tool call: init → new → prompt with tool."""
        mock_stdout = io.StringIO()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        mock_agent = MagicMock()
        mock_stream = MagicMock()

        # Simulate tool call events
        async def mock_stream_events() -> Any:
            from agents.items import ToolCallOutputItem

            # Tool call started
            event1 = MagicMock()
            event1.type = "raw_response_event"
            event1.data = MagicMock()
            event1.data.type = "response.output_item.added"
            event1.data.item = MagicMock()
            event1.data.item.type = "function_call"
            event1.data.item.name = "run_sql"
            event1.data.item.call_id = "call_001"
            yield event1

            # Tool call completed (arguments done)
            event2 = MagicMock()
            event2.type = "raw_response_event"
            event2.data = MagicMock()
            event2.data.type = "response.output_item.done"
            event2.data.item = MagicMock()
            event2.data.item.call_id = "call_001"
            yield event2

            # Tool execution result - use MagicMock that passes isinstance check
            # Create a mock ToolCallOutputItem with the attributes we need
            mock_tool_output = MagicMock(spec=ToolCallOutputItem)
            mock_tool_output.call_id = "call_001"
            mock_tool_output.output = "Query returned 15 rows"

            event3 = MagicMock()
            event3.type = "run_item_stream_event"
            event3.item = mock_tool_output
            yield event3

            # Final text response
            event4 = MagicMock()
            event4.type = "raw_response_event"
            event4.data = MagicMock()
            event4.data.type = "response.output_text.delta"
            event4.data.delta = "I found 15 transactions."
            yield event4

        mock_stream.stream_events = mock_stream_events

        final_result = MagicMock()
        final_result.final_output = "I found 15 transactions."
        mock_stream.get_final_result = MagicMock(return_value=final_result)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=mock_agent,
            notifier=notifier,
        )

        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "How many transactions?"}],
        }

        async def run_prompt() -> dict[str, Any]:
            with (
                patch("transactoid.ui.acp.handlers.prompt.Runner") as mock_runner,
                patch("transactoid.ui.acp.handlers.prompt.SQLiteSession"),
            ):
                mock_runner.run_streamed.return_value = mock_stream
                return await handler.handle_prompt(params)

        with patch("sys.stdout", mock_stdout):
            result = _run_async(run_prompt())

        assert result == {"stopReason": "end_turn"}

        output = mock_stdout.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        # Expected: tool_call, tool_call_update (in_progress),
        # tool_call_update (completed), agent_message_chunk
        assert len(lines) == 4

        notifications = [json.loads(line) for line in lines]

        # First: tool_call (pending)
        assert notifications[0]["params"]["update"]["sessionUpdate"] == "tool_call"
        assert notifications[0]["params"]["update"]["toolCallId"] == "call_001"
        assert notifications[0]["params"]["update"]["title"] == "run_sql"
        assert notifications[0]["params"]["update"]["kind"] == "execute"
        assert notifications[0]["params"]["update"]["status"] == "pending"

        # Second: tool_call_update (in_progress)
        assert (
            notifications[1]["params"]["update"]["sessionUpdate"] == "tool_call_update"
        )
        assert notifications[1]["params"]["update"]["toolCallId"] == "call_001"
        assert notifications[1]["params"]["update"]["status"] == "in_progress"

        # Third: tool_call_update (completed)
        assert (
            notifications[2]["params"]["update"]["sessionUpdate"] == "tool_call_update"
        )
        assert notifications[2]["params"]["update"]["toolCallId"] == "call_001"
        assert notifications[2]["params"]["update"]["status"] == "completed"
        assert "content" in notifications[2]["params"]["update"]

        # Fourth: agent_message_chunk
        update_type = "agent_message_chunk"
        assert notifications[3]["params"]["update"]["sessionUpdate"] == update_type


class TestACPServerTransportIntegration:
    """Integration tests for transport layer with handlers."""

    def test_transport_roundtrip_with_router(self) -> None:
        """Test JSON-RPC message parsing through transport and routing."""
        session_manager = SessionManager()
        router = RequestRouter()

        router.register("initialize", handle_initialize)

        async def session_new_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await handle_session_new(params, session_manager)

        router.register("session/new", session_new_handler)

        # Simulate JSON-RPC messages
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

        mock_stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
        mock_stdout = io.StringIO()

        async def run_server() -> list[dict[str, Any]]:
            transport = StdioTransport()
            responses: list[dict[str, Any]] = []

            with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
                # Process two messages
                for _ in range(2):
                    request = await transport.read_message()
                    params = request.params or {}
                    result = await router.dispatch(request.method, params)

                    response = JsonRpcResponse(id=request.id, result=result)
                    await transport.write_response(response)
                    responses.append(result)

            return responses

        responses = _run_async(run_server())

        # Verify initialize response
        assert responses[0]["protocolVersion"] == 1
        assert responses[0]["agentInfo"]["name"] == "transactoid"

        # Verify session/new response
        assert "sessionId" in responses[1]
        assert responses[1]["sessionId"].startswith("sess_")

        # Verify JSON-RPC responses were written
        output_lines = mock_stdout.getvalue().strip().split("\n")
        assert len(output_lines) == 2

        response1: dict[str, Any] = json.loads(output_lines[0])
        assert response1["jsonrpc"] == "2.0"
        assert response1["id"] == 1
        assert "result" in response1

        response2: dict[str, Any] = json.loads(output_lines[1])
        assert response2["jsonrpc"] == "2.0"
        assert response2["id"] == 2


class TestACPServerErrorHandling:
    """Integration tests for error handling across components."""

    def test_invalid_session_in_prompt_returns_error(self) -> None:
        """Test that prompt with invalid session returns proper error."""
        session_manager = SessionManager()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        mock_agent = MagicMock()

        handler = PromptHandler(
            session_manager=session_manager,
            agent=mock_agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": "sess_nonexistent",
            "content": [{"type": "text", "text": "Hello"}],
        }

        result = _run_async(handler.handle_prompt(params))

        assert "error" in result
        assert result["error"]["code"] == -32600
        assert "Invalid session" in result["error"]["message"]

    def test_empty_content_returns_error(self) -> None:
        """Test that prompt with empty content returns proper error."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        mock_agent = MagicMock()

        handler = PromptHandler(
            session_manager=session_manager,
            agent=mock_agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [],
        }

        result = _run_async(handler.handle_prompt(params))

        assert "error" in result
        assert result["error"]["code"] == -32602


class TestACPServerMultiSession:
    """Integration tests for multi-session scenarios."""

    def test_multiple_sessions_are_independent(self) -> None:
        """Test that multiple sessions maintain independent state."""
        session_manager = SessionManager()

        # Create two sessions
        session1_id = session_manager.create(cwd="/home/user1", mcp_servers=[])
        session2_id = session_manager.create(cwd="/home/user2", mcp_servers=[])

        # Add messages to each
        session_manager.add_message(
            session1_id, {"role": "user", "content": "Message 1"}
        )
        session_manager.add_message(
            session2_id, {"role": "user", "content": "Message 2"}
        )
        session_manager.add_message(
            session2_id, {"role": "user", "content": "Message 3"}
        )

        # Verify independence
        session1 = session_manager.get(session1_id)
        session2 = session_manager.get(session2_id)

        assert session1 is not None
        assert session2 is not None

        assert len(session1.messages) == 1
        assert len(session2.messages) == 2

        assert session1.messages[0]["content"] == "Message 1"
        assert session2.messages[0]["content"] == "Message 2"
        assert session2.messages[1]["content"] == "Message 3"

    def test_version_negotiation_with_different_clients(self) -> None:
        """Test version negotiation with different client versions."""

        async def run_negotiations() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []

            # Client with version 1
            result1 = await handle_initialize({"protocolVersion": 1})
            results.append(result1)

            # Client with higher version
            result2 = await handle_initialize({"protocolVersion": 99})
            results.append(result2)

            # Client with lower version
            result3 = await handle_initialize({"protocolVersion": 0})
            results.append(result3)

            return results

        results = _run_async(run_negotiations())

        # Version 1 client gets version 1
        assert results[0]["protocolVersion"] == 1

        # Higher version client gets agent's version (1)
        assert results[1]["protocolVersion"] == 1

        # Lower version client gets their version (0)
        assert results[2]["protocolVersion"] == 0
