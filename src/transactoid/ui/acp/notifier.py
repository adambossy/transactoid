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
        raw_input: dict[str, Any] | None = None,
        content: list[dict[str, Any]] | None = None,
        locations: list[dict[str, Any]] | None = None,
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
            raw_input: Optional structured input payload with stable schema.
            content: Optional rendered content blocks for display.
            locations: Optional file locations related to this tool call.
        """
        update: dict[str, Any] = {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_call_id,
            "title": title,
            "kind": kind,
            "status": status,
        }
        if raw_input is not None:
            update["rawInput"] = raw_input
        if content is not None:
            update["content"] = content
        if locations is not None:
            update["locations"] = locations
        await self._send_update(update)

    async def tool_call_update(
        self,
        session_id: str,
        tool_call_id: str,
        status: ToolCallStatus,
        content: list[dict[str, Any]] | None = None,
        raw_output: dict[str, Any] | None = None,
        title: str | None = None,
        kind: ToolCallKind | None = None,
        locations: list[dict[str, Any]] | None = None,
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
            raw_output: Optional structured output payload with stable schema.
            title: Optional updated title for the tool call.
            kind: Optional updated kind for the tool call.
            locations: Optional file locations related to this tool call.
        """
        update: dict[str, Any] = {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_call_id,
            "status": status,
        }
        if content is not None:
            update["content"] = content
        if raw_output is not None:
            update["rawOutput"] = raw_output
        if title is not None:
            update["title"] = title
        if kind is not None:
            update["kind"] = kind
        if locations is not None:
            update["locations"] = locations
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
