"""OpenAI Agents SDK adapter for converting tools to FunctionTool format."""

from __future__ import annotations

import json
from typing import Any

from agents.tool import FunctionTool
from agents.tool_context import ToolContext

from transactoid.tools.protocol import Tool
from transactoid.tools.registry import ToolRegistry


class OpenAIAdapter:
    """
    Adapter to convert Tool instances to OpenAI Agents SDK format.

    Creates FunctionTool instances with explicit schemas that can be passed to
    the OpenAI Agent constructor.

    Example:
        registry = ToolRegistry()
        registry.register(my_tool)

        adapter = OpenAIAdapter(registry)
        tool_functions = adapter.adapt_all()

        agent = Agent(
            name="MyAgent",
            tools=tool_functions,
            ...
        )
    """

    def __init__(self, registry: ToolRegistry) -> None:
        """
        Initialize the OpenAI adapter.

        Args:
            registry: ToolRegistry containing registered tools
        """
        self._registry = registry

    def adapt_tool(self, tool: Tool) -> FunctionTool:
        """
        Convert a Tool to an OpenAI Agents SDK FunctionTool.

        Args:
            tool: Tool instance to convert

        Returns:
            FunctionTool instance that wraps tool.execute_async()
        """

        # Create async invoke handler that parses JSON args and calls the tool
        async def on_invoke(ctx: ToolContext[Any], args_json: str) -> str:
            kwargs: dict[str, Any] = json.loads(args_json) if args_json else {}
            result = await tool.execute_async(**kwargs)
            return json.dumps(result)

        # Create FunctionTool with explicit schema from tool.input_schema
        return FunctionTool(
            name=tool.name,
            description=tool.description,
            params_json_schema=dict(tool.input_schema),
            on_invoke_tool=on_invoke,
            strict_json_schema=True,
        )

    def adapt_all(self) -> list[FunctionTool]:
        """
        Convert all registered tools to OpenAI format.

        Returns:
            List of FunctionTool instances
        """
        return [self.adapt_tool(tool) for tool in self._registry.all()]
