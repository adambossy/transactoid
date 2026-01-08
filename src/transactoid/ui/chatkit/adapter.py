"""OpenAI Agents SDK adapter for converting tools to function_tool format."""

from __future__ import annotations

from typing import Any

from agents import function_tool

from transactoid.tools.protocol import Tool
from transactoid.tools.registry import ToolRegistry


class OpenAIAdapter:
    """
    Adapter to convert Tool instances to OpenAI Agents SDK format.

    Creates @function_tool decorated wrappers that can be passed to
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

    def adapt_tool(self, tool: Tool) -> Any:
        """
        Convert a Tool to an OpenAI Agents SDK function_tool.

        Args:
            tool: Tool instance to convert

        Returns:
            FunctionTool instance that wraps tool.execute()
        """

        # Create async wrapper function with proper signature
        async def tool_wrapper(**kwargs: Any) -> dict[str, Any]:
            return await tool.execute(**kwargs)

        # Set metadata for function_tool
        tool_wrapper.__name__ = tool.name
        tool_wrapper.__doc__ = tool.description

        # Apply @function_tool decorator
        return function_tool(tool_wrapper)

    def adapt_all(self) -> list[Any]:
        """
        Convert all registered tools to OpenAI format.

        Returns:
            List of FunctionTool instances
        """
        return [self.adapt_tool(tool) for tool in self._registry.all()]
