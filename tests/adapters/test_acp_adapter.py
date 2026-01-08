"""Tests for ACP adapter."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from unittest.mock import patch

from transactoid.adapters.acp_adapter import ACPAdapter
from transactoid.tools.protocol import Tool, ToolInputSchema
from transactoid.tools.registry import ToolRegistry
from transactoid.ui.acp.notifier import UpdateNotifier
from transactoid.ui.acp.transport import StdioTransport


class MockTool:
    """Mock tool for testing."""

    def __init__(
        self,
        name: str,
        result: dict[str, Any] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._name = name
        self._result = result or {"status": "success"}
        self._raises = raises

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock tool: {self._name}"

    @property
    def input_schema(self) -> ToolInputSchema:  # type: ignore[misc]
        return {"type": "object", "properties": {}, "required": []}

    def is_async(self) -> bool:
        return False

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._raises:
            raise self._raises
        return self._result

    async def execute_async(self, **kwargs: Any) -> dict[str, Any]:
        return self.execute(**kwargs)


def _run_wrapped_tool(
    adapter: ACPAdapter, tool: Tool, **kwargs: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run a wrapped tool and capture notifications.

    Returns:
        Tuple of (result, list of captured notifications).
    """
    mock_stdout = io.StringIO()
    result: dict[str, Any] = {}

    async def run() -> dict[str, Any]:
        wrapped = adapter.wrap_tool(tool)
        return await wrapped(**kwargs)

    with patch("sys.stdout", mock_stdout):
        result = asyncio.run(run())

    output = mock_stdout.getvalue().strip()
    notifications = [json.loads(line) for line in output.split("\n") if line]
    return result, notifications


class TestACPAdapterWrapTool:
    """Tests for ACPAdapter.wrap_tool method."""

    def test_wrap_tool_sends_pending_in_progress_completed(self) -> None:
        """Test that wrap_tool sends the correct notification sequence."""
        registry = ToolRegistry()
        tool = MockTool("test_tool", result={"status": "success", "data": 42})
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test123")

        result, notifications = _run_wrapped_tool(adapter, tool)

        assert result == {"status": "success", "data": 42}
        assert len(notifications) == 3

        # First: tool_call with pending
        assert notifications[0]["params"]["update"]["sessionUpdate"] == "tool_call"
        assert notifications[0]["params"]["update"]["status"] == "pending"
        assert notifications[0]["params"]["update"]["title"] == "test_tool"

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

    def test_wrap_tool_generates_unique_call_ids(self) -> None:
        """Test that each wrapped call gets a unique tool call ID."""
        registry = ToolRegistry()
        tool = MockTool("test_tool")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test123")

        _, notifications1 = _run_wrapped_tool(adapter, tool)
        _, notifications2 = _run_wrapped_tool(adapter, tool)

        call_id_1 = notifications1[0]["params"]["update"]["toolCallId"]
        call_id_2 = notifications2[0]["params"]["update"]["toolCallId"]

        assert call_id_1.startswith("call_")
        assert call_id_2.startswith("call_")
        assert call_id_1 != call_id_2

    def test_wrap_tool_handles_execution_error(self) -> None:
        """Test that errors during execution result in failed status."""
        registry = ToolRegistry()
        tool = MockTool("test_tool", raises=ValueError("Something went wrong"))
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test123")

        result, notifications = _run_wrapped_tool(adapter, tool)

        assert result["status"] == "error"
        assert "Something went wrong" in result["error"]
        assert len(notifications) == 3

        # Final notification should be failed
        assert notifications[2]["params"]["update"]["status"] == "failed"

    def test_wrap_tool_passes_kwargs_to_execute(self) -> None:
        """Test that kwargs are passed through to the tool's execute method."""

        class KwargsCapturingTool:
            """Tool that captures kwargs for verification."""

            captured_kwargs: dict[str, Any] = {}

            @property
            def name(self) -> str:
                return "kwargs_tool"

            @property
            def description(self) -> str:
                return "Captures kwargs"

            @property
            def input_schema(self) -> ToolInputSchema:  # type: ignore[misc]
                return {"type": "object", "properties": {}, "required": []}

            def is_async(self) -> bool:
                return False

            def execute(self, **kwargs: Any) -> dict[str, Any]:
                KwargsCapturingTool.captured_kwargs = kwargs
                return {"status": "success"}

            async def execute_async(self, **kwargs: Any) -> dict[str, Any]:
                return self.execute(**kwargs)

        registry = ToolRegistry()
        tool = KwargsCapturingTool()
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test123")

        _run_wrapped_tool(adapter, tool, param1="value1", param2=42)

        assert KwargsCapturingTool.captured_kwargs == {"param1": "value1", "param2": 42}


class TestACPAdapterGetKind:
    """Tests for ACPAdapter._get_kind method."""

    def test_get_kind_sync_transactions_returns_fetch(self) -> None:
        registry = ToolRegistry()
        tool = MockTool("sync_transactions")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        _, notifications = _run_wrapped_tool(adapter, tool)

        assert notifications[0]["params"]["update"]["kind"] == "fetch"

    def test_get_kind_run_sql_returns_execute(self) -> None:
        registry = ToolRegistry()
        tool = MockTool("run_sql")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        _, notifications = _run_wrapped_tool(adapter, tool)

        assert notifications[0]["params"]["update"]["kind"] == "execute"

    def test_get_kind_recategorize_by_merchant_returns_edit(self) -> None:
        registry = ToolRegistry()
        tool = MockTool("recategorize_by_merchant")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        _, notifications = _run_wrapped_tool(adapter, tool)

        assert notifications[0]["params"]["update"]["kind"] == "edit"

    def test_get_kind_tag_transactions_returns_edit(self) -> None:
        registry = ToolRegistry()
        tool = MockTool("tag_transactions")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        _, notifications = _run_wrapped_tool(adapter, tool)

        assert notifications[0]["params"]["update"]["kind"] == "edit"

    def test_get_kind_unknown_tool_returns_other(self) -> None:
        registry = ToolRegistry()
        tool = MockTool("unknown_tool")
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        _, notifications = _run_wrapped_tool(adapter, tool)

        assert notifications[0]["params"]["update"]["kind"] == "other"


class TestACPAdapterWrapAll:
    """Tests for ACPAdapter.wrap_all method."""

    def test_wrap_all_returns_dict_of_wrapped_tools(self) -> None:
        registry = ToolRegistry()
        tool1 = MockTool("tool_one")
        tool2 = MockTool("tool_two")
        registry.register(tool1)
        registry.register(tool2)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        wrapped = adapter.wrap_all()

        assert "tool_one" in wrapped
        assert "tool_two" in wrapped
        assert callable(wrapped["tool_one"])
        assert callable(wrapped["tool_two"])

    def test_wrap_all_empty_registry_returns_empty_dict(self) -> None:
        registry = ToolRegistry()

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        wrapped = adapter.wrap_all()

        assert wrapped == {}

    def test_wrap_all_tools_execute_correctly(self) -> None:
        """Test that tools from wrap_all actually execute."""
        registry = ToolRegistry()
        tool = MockTool("my_tool", result={"status": "success", "value": "test"})
        registry.register(tool)

        transport = StdioTransport()
        notifier = UpdateNotifier(transport)
        adapter = ACPAdapter(registry, notifier, "sess_test")

        wrapped = adapter.wrap_all()
        mock_stdout = io.StringIO()

        async def run() -> dict[str, Any]:
            return await wrapped["my_tool"]()

        with patch("sys.stdout", mock_stdout):
            result = asyncio.run(run())

        assert result == {"status": "success", "value": "test"}
