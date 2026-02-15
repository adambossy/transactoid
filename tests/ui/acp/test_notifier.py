"""Tests for ACP UpdateNotifier."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from unittest.mock import patch

from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.tool_payloads import SCHEMA_INPUT_V1, SCHEMA_OUTPUT_V1
from transactoid.ui.acp.transport import StdioTransport


def _capture_notification(notifier_call: Any) -> dict[str, Any]:
    """Run a notifier call and capture the JSON output."""
    mock_stdout = io.StringIO()

    async def run() -> None:
        await notifier_call

    with patch("sys.stdout", mock_stdout):
        asyncio.run(run())

    output = mock_stdout.getvalue()
    parsed: Any = json.loads(output.strip())
    if not isinstance(parsed, dict):
        msg = f"Expected notification payload dict; got {type(parsed).__name__}"
        raise TypeError(msg)
    return parsed


class TestUpdateNotifierToolCall:
    """Tests for UpdateNotifier.tool_call method."""

    def test_tool_call_sends_pending_notification(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="Querying database",
                kind="execute",
                status="pending",
            )
        )

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call_001",
                    "title": "Querying database",
                    "kind": "execute",
                    "status": "pending",
                }
            },
        }
        assert parsed == expected

    def test_tool_call_with_fetch_kind(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_xyz",
                tool_call_id="call_002",
                title="Fetching transactions",
                kind="fetch",
                status="pending",
            )
        )

        assert parsed["params"]["update"]["kind"] == "fetch"
        assert parsed["params"]["update"]["title"] == "Fetching transactions"

    def test_tool_call_with_edit_kind(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_xyz",
                tool_call_id="call_003",
                title="Updating category",
                kind="edit",
                status="pending",
            )
        )

        assert parsed["params"]["update"]["kind"] == "edit"


class TestUpdateNotifierToolCallUpdate:
    """Tests for UpdateNotifier.tool_call_update method."""

    def test_tool_call_update_in_progress(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="in_progress",
            )
        )

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call_001",
                    "status": "in_progress",
                }
            },
        }
        assert parsed == expected

    def test_tool_call_update_completed_with_content(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="completed",
                content=[{"type": "text", "text": "Query returned 15 rows"}],
            )
        )

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call_001",
                    "status": "completed",
                    "content": [{"type": "text", "text": "Query returned 15 rows"}],
                }
            },
        }
        assert parsed == expected

    def test_tool_call_update_failed_with_error_content(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="failed",
                content=[{"type": "text", "text": "Database connection error"}],
            )
        )

        assert parsed["params"]["update"]["status"] == "failed"
        assert parsed["params"]["update"]["content"] == [
            {"type": "text", "text": "Database connection error"}
        ]

    def test_tool_call_update_omits_content_when_none(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="in_progress",
                content=None,
            )
        )

        assert "content" not in parsed["params"]["update"]


class TestUpdateNotifierAgentMessageChunk:
    """Tests for UpdateNotifier.agent_message_chunk method."""

    def test_agent_message_chunk_sends_text_content(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.agent_message_chunk(
                session_id="sess_abc123",
                content={"type": "text", "text": "Based on your transactions..."},
            )
        )

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {
                        "type": "text",
                        "text": "Based on your transactions...",
                    },
                }
            },
        }
        assert parsed == expected


class TestUpdateNotifierAgentThoughtChunk:
    """Tests for UpdateNotifier.agent_thought_chunk method."""

    def test_agent_thought_chunk_sends_thinking_content(self) -> None:
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.agent_thought_chunk(
                session_id="sess_abc123",
                content={"type": "thinking", "text": "Let me analyze this..."},
            )
        )

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "thinking", "text": "Let me analyze this..."},
                }
            },
        }
        assert parsed == expected


class TestUpdateNotifierIntegration:
    """Integration tests for UpdateNotifier with multiple notifications."""

    def test_multiple_notifications_in_sequence(self) -> None:
        """Test a typical tool call lifecycle: pending -> in_progress -> completed."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        mock_stdout = io.StringIO()

        async def run_sequence() -> None:
            await notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="Running query",
                kind="execute",
                status="pending",
            )
            await notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="in_progress",
            )
            await notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="completed",
                content=[{"type": "text", "text": "Done"}],
            )

        with patch("sys.stdout", mock_stdout):
            asyncio.run(run_sequence())

        lines = mock_stdout.getvalue().strip().split("\n")
        assert len(lines) == 3

        notifications = [json.loads(line) for line in lines]

        # First: tool_call with pending
        assert notifications[0]["params"]["update"]["sessionUpdate"] == "tool_call"
        assert notifications[0]["params"]["update"]["status"] == "pending"

        # Second: tool_call_update with in_progress
        assert (
            notifications[1]["params"]["update"]["sessionUpdate"] == "tool_call_update"
        )
        assert notifications[1]["params"]["update"]["status"] == "in_progress"

        # Third: tool_call_update with completed
        assert (
            notifications[2]["params"]["update"]["sessionUpdate"] == "tool_call_update"
        )
        assert notifications[2]["params"]["update"]["status"] == "completed"
        assert "content" in notifications[2]["params"]["update"]

    def test_interleaved_tool_calls_and_agent_message_chunks(self) -> None:
        """Test interleaving tool call updates with message streaming."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        mock_stdout = io.StringIO()

        async def run_sequence() -> None:
            await notifier.agent_message_chunk(
                session_id="sess_abc123",
                content={"type": "text", "text": "Let me check that..."},
            )
            await notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="DB query",
                kind="execute",
                status="pending",
            )
            await notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="completed",
                content=[{"type": "text", "text": "5 results"}],
            )
            await notifier.agent_message_chunk(
                session_id="sess_abc123",
                content={"type": "text", "text": "I found 5 transactions."},
            )

        with patch("sys.stdout", mock_stdout):
            asyncio.run(run_sequence())

        lines = mock_stdout.getvalue().strip().split("\n")
        assert len(lines) == 4

        notifications = [json.loads(line) for line in lines]

        update_type = "agent_message_chunk"
        assert notifications[0]["params"]["update"]["sessionUpdate"] == update_type
        assert notifications[1]["params"]["update"]["sessionUpdate"] == "tool_call"
        assert (
            notifications[2]["params"]["update"]["sessionUpdate"] == "tool_call_update"
        )
        assert notifications[3]["params"]["update"]["sessionUpdate"] == update_type


class TestUpdateNotifierRichPayloads:
    """Tests for rich payload fields (rawInput, rawOutput, etc.)."""

    def test_tool_call_with_raw_input(self) -> None:
        """Test tool_call includes rawInput when provided."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        raw_input = {
            "schema": SCHEMA_INPUT_V1,
            "tool": "run_sql",
            "arguments": {"query": "SELECT 1"},
        }

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="run_sql",
                kind="execute",
                status="pending",
                raw_input=raw_input,
            )
        )

        update = parsed["params"]["update"]
        assert "rawInput" in update
        assert update["rawInput"] == raw_input

    def test_tool_call_with_content(self) -> None:
        """Test tool_call includes content when provided."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        content = [
            {"type": "content", "content": {"type": "text", "text": "Tool: run_sql"}}
        ]

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="run_sql",
                kind="execute",
                status="pending",
                content=content,
            )
        )

        update = parsed["params"]["update"]
        assert "content" in update
        assert update["content"] == content

    def test_tool_call_omits_optional_fields_when_none(self) -> None:
        """Test tool_call omits rawInput, content, locations when None."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call(
                session_id="sess_abc123",
                tool_call_id="call_001",
                title="run_sql",
                kind="execute",
                status="pending",
                raw_input=None,
                content=None,
                locations=None,
            )
        )

        update = parsed["params"]["update"]
        assert "rawInput" not in update
        assert "content" not in update
        assert "locations" not in update

    def test_tool_call_update_with_raw_output(self) -> None:
        """Test tool_call_update includes rawOutput when provided."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        raw_output = {
            "schema": SCHEMA_OUTPUT_V1,
            "status": "completed",
            "result": {"rows": [], "count": 0},
        }

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="completed",
                raw_output=raw_output,
            )
        )

        update = parsed["params"]["update"]
        assert "rawOutput" in update
        assert update["rawOutput"] == raw_output

    def test_tool_call_update_with_all_optional_fields(self) -> None:
        """Test tool_call_update with all optional fields."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        raw_output = {"schema": SCHEMA_OUTPUT_V1, "status": "completed", "result": {}}
        content = [{"type": "text", "text": "Done"}]
        locations = [{"path": "/app/db.py", "line": 42}]

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="completed",
                raw_output=raw_output,
                content=content,
                title="Updated title",
                kind="fetch",
                locations=locations,
            )
        )

        update = parsed["params"]["update"]
        assert update["rawOutput"] == raw_output
        assert update["content"] == content
        assert update["title"] == "Updated title"
        assert update["kind"] == "fetch"
        assert update["locations"] == locations

    def test_tool_call_update_omits_optional_fields_when_none(self) -> None:
        """Test tool_call_update omits optional fields when None."""
        transport = StdioTransport()
        notifier = UpdateNotifier(transport)

        parsed = _capture_notification(
            notifier.tool_call_update(
                session_id="sess_abc123",
                tool_call_id="call_001",
                status="in_progress",
                raw_output=None,
                content=None,
                title=None,
                kind=None,
                locations=None,
            )
        )

        update = parsed["params"]["update"]
        assert "rawOutput" not in update
        assert "content" not in update
        assert "title" not in update
        assert "kind" not in update
        assert "locations" not in update
