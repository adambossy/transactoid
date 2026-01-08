"""ACP adapter for tool execution with status updates.

Wraps ToolRegistry tools to emit ACP session/update notifications during
tool execution, enabling real-time progress tracking in ACP-compatible clients.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
import uuid

from transactoid.tools.protocol import Tool
from transactoid.tools.registry import ToolRegistry
from transactoid.ui.acp.notifier import ToolCallKind, ToolCallStatus, UpdateNotifier


class ACPAdapter:
    """Wrap tools to emit ACP updates during execution.

    The adapter intercepts tool executions and sends appropriate
    session/update notifications:
    - tool_call with "pending" status when execution starts
    - tool_call_update with "in_progress" status during execution
    - tool_call_update with "completed" or "failed" status when done

    Example:
        adapter = ACPAdapter(registry, notifier, session_id)
        wrapped_tool = adapter.wrap_tool(my_tool)
        result = await wrapped_tool(param1="value")
    """

    def __init__(
        self,
        registry: ToolRegistry,
        notifier: UpdateNotifier,
        session_id: str,
    ) -> None:
        """Initialize the ACP adapter.

        Args:
            registry: ToolRegistry containing registered tools.
            notifier: UpdateNotifier for sending ACP notifications.
            session_id: Session identifier for all notifications.
        """
        self._registry = registry
        self._notifier = notifier
        self._session_id = session_id

    def wrap_tool(
        self, tool: Tool
    ) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        """Wrap a tool to emit ACP updates during execution.

        Creates an async wrapper that sends tool_call and tool_call_update
        notifications before, during, and after tool execution.

        Args:
            tool: Tool instance to wrap.

        Returns:
            Async callable that executes the tool with ACP notifications.
        """

        async def wrapped(**kwargs: Any) -> dict[str, Any]:
            # Generate unique tool call ID
            call_id = f"call_{uuid.uuid4().hex[:12]}"

            # Notify: pending
            await self._notifier.tool_call(
                session_id=self._session_id,
                tool_call_id=call_id,
                title=tool.name,
                kind=self._get_kind(tool.name),
                status="pending",
            )

            # Notify: in_progress
            await self._notifier.tool_call_update(
                session_id=self._session_id,
                tool_call_id=call_id,
                status="in_progress",
            )

            # Execute tool
            status: ToolCallStatus
            try:
                result = await tool.execute(**kwargs)
                status = "completed"
            except Exception as e:
                result = {"status": "error", "error": str(e)}
                status = "failed"

            # Notify: completed/failed
            await self._notifier.tool_call_update(
                session_id=self._session_id,
                tool_call_id=call_id,
                status=status,
                content=[{"type": "text", "text": str(result)}],
            )

            return result

        return wrapped

    def wrap_all(
        self,
    ) -> dict[str, Callable[..., Coroutine[Any, Any, dict[str, Any]]]]:
        """Wrap all registered tools for ACP execution.

        Returns:
            Dict mapping tool names to wrapped async callables.
        """
        return {tool.name: self.wrap_tool(tool) for tool in self._registry.all()}

    def _get_kind(self, tool_name: str) -> ToolCallKind:
        """Map tool name to ACP kind.

        Args:
            tool_name: Name of the tool.

        Returns:
            ACP kind value (fetch, execute, edit, or other).
        """
        kind_map: dict[str, ToolCallKind] = {
            "sync_transactions": "fetch",
            "run_sql": "execute",
            "recategorize_by_merchant": "edit",
            "tag_transactions": "edit",
        }
        return kind_map.get(tool_name, "other")
