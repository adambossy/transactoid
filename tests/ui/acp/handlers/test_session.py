"""Tests for ACP session handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from transactoid.ui.acp.handlers.session import (
    Session,
    SessionManager,
    handle_session_new,
)


def _run_async(coro: Any) -> Any:
    """Run an async function synchronously."""
    return asyncio.run(coro)


class TestSession:
    """Tests for Session dataclass."""

    def test_session_has_required_fields(self) -> None:
        """Test that Session has all required fields."""
        session = Session(
            id="sess_abc123",
            cwd="/home/user",
            mcp_servers=[],
        )

        assert session.id == "sess_abc123"
        assert session.cwd == "/home/user"
        assert session.mcp_servers == []
        assert session.messages == []

    def test_session_messages_default_to_empty_list(self) -> None:
        """Test that messages default to empty list."""
        session = Session(
            id="sess_abc123",
            cwd="/home/user",
            mcp_servers=[],
        )

        assert session.messages == []

    def test_session_can_have_messages(self) -> None:
        """Test that Session can be created with messages."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        session = Session(
            id="sess_abc123",
            cwd="/home/user",
            mcp_servers=[],
            messages=messages,
        )

        assert len(session.messages) == 2


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_create_returns_session_id(self) -> None:
        """Test that create returns a session ID."""
        manager = SessionManager()

        session_id = manager.create(cwd="/home/user", mcp_servers=[])

        assert session_id.startswith("sess_")
        assert len(session_id) == 17  # "sess_" + 12 hex chars

    def test_create_generates_unique_ids(self) -> None:
        """Test that each create generates a unique ID."""
        manager = SessionManager()

        id1 = manager.create(cwd="/home/user1", mcp_servers=[])
        id2 = manager.create(cwd="/home/user2", mcp_servers=[])
        id3 = manager.create(cwd="/home/user3", mcp_servers=[])

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    def test_get_returns_session_by_id(self) -> None:
        """Test that get returns the correct session."""
        manager = SessionManager()
        session_id = manager.create(cwd="/home/user", mcp_servers=[])

        session = manager.get(session_id)

        assert session is not None
        assert session.id == session_id
        assert session.cwd == "/home/user"

    def test_get_returns_none_for_unknown_id(self) -> None:
        """Test that get returns None for unknown session ID."""
        manager = SessionManager()

        session = manager.get("sess_unknown123")

        assert session is None

    def test_get_preserves_mcp_servers(self) -> None:
        """Test that get returns session with original mcp_servers."""
        manager = SessionManager()
        mcp_servers: list[dict[str, Any]] = [
            {"name": "server1", "url": "http://localhost:3000"},
        ]

        session_id = manager.create(cwd="/home/user", mcp_servers=mcp_servers)
        session = manager.get(session_id)

        assert session is not None
        assert session.mcp_servers == mcp_servers

    def test_add_message_returns_true_for_valid_session(self) -> None:
        """Test that add_message returns True for valid session."""
        manager = SessionManager()
        session_id = manager.create(cwd="/home/user", mcp_servers=[])

        result = manager.add_message(session_id, {"role": "user", "content": "Hello"})

        assert result is True

    def test_add_message_returns_false_for_unknown_session(self) -> None:
        """Test that add_message returns False for unknown session."""
        manager = SessionManager()

        result = manager.add_message(
            "sess_unknown123", {"role": "user", "content": "Hello"}
        )

        assert result is False

    def test_add_message_appends_to_history(self) -> None:
        """Test that add_message appends to message history."""
        manager = SessionManager()
        session_id = manager.create(cwd="/home/user", mcp_servers=[])

        manager.add_message(session_id, {"role": "user", "content": "Hello"})
        manager.add_message(session_id, {"role": "assistant", "content": "Hi there"})

        session = manager.get(session_id)
        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert session.messages[1]["role"] == "assistant"

    def test_len_returns_session_count(self) -> None:
        """Test that len returns the number of sessions."""
        manager = SessionManager()

        assert len(manager) == 0

        manager.create(cwd="/home/user1", mcp_servers=[])
        assert len(manager) == 1

        manager.create(cwd="/home/user2", mcp_servers=[])
        assert len(manager) == 2

    def test_contains_returns_true_for_existing_session(self) -> None:
        """Test that 'in' returns True for existing session."""
        manager = SessionManager()
        session_id = manager.create(cwd="/home/user", mcp_servers=[])

        assert session_id in manager

    def test_contains_returns_false_for_unknown_session(self) -> None:
        """Test that 'in' returns False for unknown session."""
        manager = SessionManager()

        assert "sess_unknown123" not in manager


class TestHandleSessionNew:
    """Tests for handle_session_new function."""

    def test_handle_session_new_returns_session_id(self) -> None:
        """Test that handle_session_new returns a session ID."""
        manager = SessionManager()
        params: dict[str, Any] = {"cwd": "/home/user"}

        result = _run_async(handle_session_new(params, manager))

        assert "sessionId" in result
        assert result["sessionId"].startswith("sess_")

    def test_handle_session_new_creates_session(self) -> None:
        """Test that handle_session_new creates a session in the manager."""
        manager = SessionManager()
        params: dict[str, Any] = {"cwd": "/home/user"}

        result = _run_async(handle_session_new(params, manager))

        session = manager.get(result["sessionId"])
        assert session is not None
        assert session.cwd == "/home/user"

    def test_handle_session_new_with_mcp_servers(self) -> None:
        """Test that handle_session_new handles mcpServers parameter."""
        manager = SessionManager()
        params: dict[str, Any] = {
            "cwd": "/home/user",
            "mcpServers": [{"name": "server1", "url": "http://localhost:3000"}],
        }

        result = _run_async(handle_session_new(params, manager))

        session = manager.get(result["sessionId"])
        assert session is not None
        assert len(session.mcp_servers) == 1
        assert session.mcp_servers[0]["name"] == "server1"

    def test_handle_session_new_defaults_to_empty_cwd(self) -> None:
        """Test that handle_session_new defaults to empty cwd."""
        manager = SessionManager()
        params: dict[str, Any] = {}

        result = _run_async(handle_session_new(params, manager))

        session = manager.get(result["sessionId"])
        assert session is not None
        assert session.cwd == ""

    def test_handle_session_new_defaults_to_empty_mcp_servers(self) -> None:
        """Test that handle_session_new defaults to empty mcp_servers."""
        manager = SessionManager()
        params: dict[str, Any] = {"cwd": "/home/user"}

        result = _run_async(handle_session_new(params, manager))

        session = manager.get(result["sessionId"])
        assert session is not None
        assert session.mcp_servers == []
