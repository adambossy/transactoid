"""MCP (Model Context Protocol) adapter for Anthropic MCP SDK."""

from __future__ import annotations

from typing import Any

from tools.protocol import Tool
from tools.registry import ToolRegistry


class MCPToolDefinition:
    """MCP tool definition for Anthropic MCP SDK."""

    def __init__(
        self, name: str, description: str, input_schema: dict[str, Any]
    ) -> None:
        """
        Initialize MCP tool definition.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON Schema for tool parameters
        """
        self.name = name
        self.description = description
        self.input_schema = input_schema


class MCPAdapter:
    """
    Convert Tool instances to Anthropic MCP tool definition format.

    Creates tool definitions and handlers for MCP server integration.

    Example:
        registry = ToolRegistry()
        registry.register(my_tool)

        adapter = MCPAdapter(registry)
        tool_defs = adapter.adapt_all()

        # Register with MCP server
        for tool_def in tool_defs:
            server.register_tool(tool_def.name, tool_def.description, ...)
    """

    def __init__(self, registry: ToolRegistry) -> None:
        """
        Initialize the MCP adapter.

        Args:
            registry: ToolRegistry containing registered tools
        """
        self._registry = registry

    def adapt_tool(self, tool: Tool) -> MCPToolDefinition:
        """
        Convert Tool to MCP tool definition.

        Args:
            tool: Tool instance to convert

        Returns:
            MCPToolDefinition with name, description, and schema
        """
        # Cast ToolInputSchema to dict[str, Any] for compatibility
        input_schema: dict[str, Any] = dict(tool.input_schema)
        return MCPToolDefinition(
            name=tool.name,
            description=tool.description,
            input_schema=input_schema,
        )

    def adapt_all(self) -> list[MCPToolDefinition]:
        """
        Convert all registered tools to MCP format.

        Returns:
            List of MCPToolDefinition instances
        """
        return [self.adapt_tool(tool) for tool in self._registry.all()]

    def create_handler(self, tool_name: str) -> Any:
        """
        Create async handler for MCP server tool registration.

        Args:
            tool_name: Name of tool to create handler for

        Returns:
            Async handler function that executes the tool

        Raises:
            ValueError: If tool not found in registry
        """
        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found in registry")

        async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            """
            MCP handler that executes tool with given arguments.

            Args:
                arguments: Tool arguments dict

            Returns:
                Tool execution result
            """
            # MCP handlers are async and receive arguments dict
            return tool.execute(**arguments)

        return handler
