from __future__ import annotations

import json
from typing import Any

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.tools.registry import ToolRegistry


class OpenAIToolAdapter:
    """Adapt shared ToolRegistry tools to OpenAI Agents SDK FunctionTool."""

    def __init__(self, *, registry: ToolRegistry, invoker: SharedToolInvoker) -> None:
        self._registry = registry
        self._invoker = invoker

    def adapt_all(self) -> list[Any]:
        """Return all registered tools as FunctionTool definitions."""
        return [self._adapt_one(tool_name) for tool_name in self._tool_names()]

    def _tool_names(self) -> list[str]:
        return [tool.name for tool in self._registry.all()]

    def _adapt_one(self, tool_name: str) -> Any:
        from agents.tool import FunctionTool

        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found in registry: {tool_name}")

        async def on_invoke(_ctx: Any, args_json: str) -> str:
            args: dict[str, Any] = json.loads(args_json) if args_json else {}
            result = await self._invoker.invoke(tool_name=tool_name, args=args)
            return json.dumps(result)

        return FunctionTool(
            name=tool.name,
            description=tool.description,
            params_json_schema=dict(tool.input_schema),
            on_invoke_tool=on_invoke,
            strict_json_schema=True,
        )
