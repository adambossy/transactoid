"""ACP session/update notification sender.

Sends JSON-RPC notifications for real-time session updates including:
- tool_call: Reports when a tool call starts (pending status)
- tool_call_update: Reports tool call status changes (in_progress, completed, failed)
- message_delta: Reports streaming text responses
"""

from __future__ import annotations

from typing import Any, Literal

from transactoid.ui.acp.transport import JsonRpcNotification, StdioTransport

ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]
ToolCallKind = Literal["execute", "fetch", "edit", "other"]


class UpdateNotifier:
    """Send session/update notifications via JSON-RPC.

    Wraps the transport layer to provide typed methods for sending
    ACP-compliant session update notifications.
    """

    def __init__(self, transport: StdioTransport) -> None:
        """Initialize the notifier with a transport.

        Args:
            transport: The StdioTransport to use for writing notifications.
        """
        self._transport = transport

    async def tool_call(
        self,
        session_id: str,
        tool_call_id: str,
        title: str,
        kind: ToolCallKind,
        status: ToolCallStatus,
    ) -> None:
        """Send a tool_call update notification.

        Reports that a tool call has started. This is typically sent with
        status="pending" when a tool invocation begins.

        Args:
            session_id: The session identifier (currently unused but kept
                for API consistency and future session-scoped notifications).
            tool_call_id: Unique identifier for this tool call.
            title: Human-readable title describing the tool operation.
            kind: Category of tool operation (execute, fetch, edit, other).
            status: Current status of the tool call.
        """
        await self._send_update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "title": title,
                "kind": kind,
                "status": status,
            }
        )

    async def tool_call_update(
        self,
        session_id: str,
        tool_call_id: str,
        status: ToolCallStatus,
        content: list[dict[str, Any]] | None = None,
    ) -> None:
        """Send a tool_call_update notification.

        Reports a status change for an existing tool call. Used for
        transitions like pending -> in_progress -> completed/failed.

        Args:
            session_id: The session identifier (currently unused but kept
                for API consistency and future session-scoped notifications).
            tool_call_id: Unique identifier for the tool call being updated.
            status: New status of the tool call.
            content: Optional content blocks with tool output, typically
                included when status is "completed" or "failed".
        """
        update: dict[str, Any] = {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_call_id,
            "status": status,
        }
        if content is not None:
            update["content"] = content
        await self._send_update(update)

    async def agent_message_chunk(
        self,
        session_id: str,
        content: dict[str, Any],
    ) -> None:
        """Send an agent_message_chunk notification.

        Reports streaming text content from the agent's response.
        Used to stream partial responses to the client in real-time.

        Args:
            session_id: The session identifier (currently unused but kept
                for API consistency and future session-scoped notifications).
            content: Content block containing the chunk, typically
                {"type": "text", "text": "..."}.
        """
        await self._send_update(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": content,
            }
        )

    async def agent_thought_chunk(
        self,
        session_id: str,
        content: dict[str, Any],
    ) -> None:
        """Send an agent_thought_chunk notification.

        Reports streaming thinking/reasoning content from the agent.
        Used for chain-of-thought or reasoning visibility.

        Args:
            session_id: The session identifier (currently unused but kept
                for API consistency and future session-scoped notifications).
            content: Content block containing the thought chunk, typically
                {"type": "thinking", "text": "..."}.
        """
        await self._send_update(
            {
                "sessionUpdate": "agent_thought_chunk",
                "content": content,
            }
        )

    async def _send_update(self, update: dict[str, Any]) -> None:
        """Send a session/update notification.

        Internal method that wraps the update payload in a JSON-RPC
        notification and writes it to the transport.

        Args:
            update: The update payload to send.
        """
        notification = JsonRpcNotification(
            method="session/update",
            params={"update": update},
        )
        await self._transport.write_notification(notification)
