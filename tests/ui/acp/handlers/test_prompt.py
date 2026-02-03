"""Tests for ACP prompt handler."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from transactoid.ui.acp.handlers.prompt import PromptHandler
from transactoid.ui.acp.handlers.session import SessionManager
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.transport import StdioTransport


def _run_async(coro: Any) -> Any:
    """Run an async function synchronously."""
    return asyncio.run(coro)


class TestPromptHandlerInit:
    """Tests for PromptHandler initialization."""

    def test_prompt_handler_accepts_dependencies(self) -> None:
        """Test that PromptHandler accepts required dependencies."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        assert handler._sessions is session_manager
        assert handler._agent is agent
        assert handler._notifier is notifier


class TestPromptHandlerValidation:
    """Tests for PromptHandler input validation."""

    def test_handle_prompt_returns_error_for_invalid_session(self) -> None:
        """Test that handle_prompt returns error for invalid session."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": "sess_invalid123",
            "content": [{"type": "text", "text": "Hello"}],
        }

        result = _run_async(handler.handle_prompt(params))

        assert "error" in result
        assert result["error"]["code"] == -32600
        assert "Invalid session" in result["error"]["message"]

    def test_handle_prompt_returns_error_for_empty_content(self) -> None:
        """Test that handle_prompt returns error for empty content."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [],
        }

        result = _run_async(handler.handle_prompt(params))

        assert "error" in result
        assert result["error"]["code"] == -32602
        assert "No text content" in result["error"]["message"]

    def test_handle_prompt_returns_error_for_non_text_content(self) -> None:
        """Test that handle_prompt returns error for non-text content only."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "image", "data": "..."}],
        }

        result = _run_async(handler.handle_prompt(params))

        assert "error" in result
        assert result["error"]["code"] == -32602


class TestPromptHandlerGetKind:
    """Tests for PromptHandler._get_kind method."""

    def test_get_kind_returns_fetch_for_sync(self) -> None:
        """Test that _get_kind returns 'fetch' for sync_transactions."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        assert handler._get_kind("sync_transactions") == "fetch"
        assert handler._get_kind("list_accounts") == "fetch"

    def test_get_kind_returns_execute_for_sql(self) -> None:
        """Test that _get_kind returns 'execute' for run_sql."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        assert handler._get_kind("run_sql") == "execute"

    def test_get_kind_returns_edit_for_mutations(self) -> None:
        """Test that _get_kind returns 'edit' for mutation tools."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        assert handler._get_kind("recategorize_merchant") == "edit"
        assert handler._get_kind("tag_transactions") == "edit"

    def test_get_kind_returns_other_for_unknown(self) -> None:
        """Test that _get_kind returns 'other' for unknown tools."""
        session_manager = SessionManager()
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        assert handler._get_kind("unknown_tool") == "other"
        assert handler._get_kind("some_new_tool") == "other"


class TestPromptHandlerIntegration:
    """Integration tests for PromptHandler with mocked agent."""

    @pytest.fixture
    def mock_stream(self) -> MagicMock:
        """Create a mock stream with async iterator."""
        stream = MagicMock()

        # Create an async iterator that yields no events
        async def empty_events() -> Any:
            return
            yield  # Make it a generator

        stream.stream_events = empty_events

        # Mock get_final_result
        final_result = MagicMock()
        final_result.final_output = "Test response"
        stream.get_final_result = MagicMock(return_value=final_result)

        return stream

    def test_handle_prompt_returns_end_turn_on_success(
        self, mock_stream: MagicMock
    ) -> None:
        """Test that handle_prompt returns stopReason end_turn on success."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "Hello"}],
        }

        with (
            patch("transactoid.ui.acp.handlers.prompt.Runner") as mock_runner,
            patch("transactoid.ui.acp.handlers.prompt.SQLiteSession"),
        ):
            mock_runner.run_streamed.return_value = mock_stream

            with patch("sys.stdout"):
                result = _run_async(handler.handle_prompt(params))

        assert result == {"stopReason": "end_turn"}

    def test_handle_prompt_adds_user_message_to_history(
        self, mock_stream: MagicMock
    ) -> None:
        """Test that handle_prompt adds user message to session history."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": "What is my balance?"}],
        }

        with (
            patch("transactoid.ui.acp.handlers.prompt.Runner") as mock_runner,
            patch("transactoid.ui.acp.handlers.prompt.SQLiteSession"),
        ):
            mock_runner.run_streamed.return_value = mock_stream

            with patch("sys.stdout"):
                _run_async(handler.handle_prompt(params))

        session = session_manager.get(session_id)
        assert session is not None
        assert len(session.messages) >= 1
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "What is my balance?"

    def test_handle_prompt_extracts_text_from_first_block(
        self, mock_stream: MagicMock
    ) -> None:
        """Test that handle_prompt uses first text block only."""
        session_manager = SessionManager()
        session_id = session_manager.create(cwd="/home/user", mcp_servers=[])
        agent = MagicMock()
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        handler = PromptHandler(
            session_manager=session_manager,
            agent=agent,
            notifier=notifier,
        )

        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [
                {"type": "image", "data": "..."},
                {"type": "text", "text": "First text"},
                {"type": "text", "text": "Second text"},
            ],
        }

        with (
            patch("transactoid.ui.acp.handlers.prompt.Runner") as mock_runner,
            patch("transactoid.ui.acp.handlers.prompt.SQLiteSession"),
        ):
            mock_runner.run_streamed.return_value = mock_stream

            with patch("sys.stdout"):
                _run_async(handler.handle_prompt(params))

        session = session_manager.get(session_id)
        assert session is not None
        # Should use "First text" not "Second text"
        assert session.messages[0]["content"] == "First text"
