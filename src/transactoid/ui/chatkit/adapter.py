"""ChatKit adapter for OpenAI ChatKit SDK."""

from __future__ import annotations

from typing import Any

from transactoid.tools.protocol import Tool
from transactoid.tools.registry import ToolRegistry


class ChatKitAdapter:
    """
    Convert Tool instances to ChatKit tool registration format.

    Creates tool definitions that can be used with ChatKit's
    OpenAI Agents SDK integration.

    Example:
        registry = ToolRegistry()
        registry.register(my_tool)

        adapter = ChatKitAdapter(registry)
        tools = adapter.adapt_all()

        # Use in ChatKit server respond() method
        agent = Agent(
            name="MyAgent",
            tools=tools,
            ...
        )
    """

    def __init__(self, registry: ToolRegistry) -> None:
        """
        Initialize the ChatKit adapter.

        Args:
            registry: ToolRegistry containing registered tools
        """
        self._registry = registry

    def adapt_tool(self, tool: Tool) -> dict[str, Any]:
        """
        Convert a Tool to ChatKit tool registration format.

        ChatKit uses a similar format to OpenAI Agents SDK but wrapped
        in the ChatKitServer.respond() method context.

        Args:
            tool: Tool instance to convert

        Returns:
            Dict with tool metadata and handler function
        """
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "handler": lambda **kwargs: tool.execute(**kwargs),
        }

    def adapt_all(self) -> list[dict[str, Any]]:
        """
        Convert all registered tools to ChatKit format.

        Returns:
            List of tool definition dicts
        """
        return [self.adapt_tool(tool) for tool in self._registry.all()]
