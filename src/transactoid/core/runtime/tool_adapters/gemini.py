from __future__ import annotations

import json
from typing import Any

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.tools.registry import ToolRegistry


class GeminiToolAdapter:
    """Adapt shared ToolRegistry tools to Google ADK FunctionTool objects."""

    def __init__(self, *, registry: ToolRegistry, invoker: SharedToolInvoker) -> None:
        self._registry = registry
        self._invoker = invoker

    def adapt_all(self) -> list[Any]:
        """Return all registered tools as ADK function tools."""
        tools: list[Any] = []
        for tool in self._registry.all():
            tool_obj = self._adapt_one(tool_name=tool.name)
            tools.append(tool_obj)
        return tools

    def _adapt_one(self, *, tool_name: str) -> Any:
        from google.adk.tools.function_tool import FunctionTool

        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found in registry: {tool_name}")

        schema_json = json.dumps(tool.input_schema, sort_keys=True)

        if not tool.input_schema.get("properties"):

            async def tool_func_no_args() -> dict[str, Any]:
                return await self._invoker.invoke(tool_name=tool_name, args={})

            tool_func_no_args.__name__ = tool.name
            tool_func_no_args.__doc__ = tool.description
            return FunctionTool(tool_func_no_args)

        async def tool_func_with_args(args: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(args, dict):
                type_name = type(args).__name__
                return {
                    "status": "error",
                    "error": (f"Expected dict args for {tool_name}; got {type_name}"),
                }
            return await self._invoker.invoke(tool_name=tool_name, args=args)

        tool_func_with_args.__name__ = tool.name
        tool_func_with_args.__doc__ = (
            f"{tool.description}\n\n"
            "Arguments must match this JSON schema:\n"
            f"{schema_json}"
        )
        return FunctionTool(tool_func_with_args)
