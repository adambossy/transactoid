"""Central registry for managing tool instances."""

from __future__ import annotations

from typing import Any

from transactoid.tools.protocol import Tool


class ToolRegistry:
    """
    Registry for managing tool instances.

    Provides:
    - Central access to all tools
    - Lookup by name
    - Iteration over tools
    - Execute tools by name (sync and async)

    Example:
        registry = ToolRegistry()

        # Register tools
        registry.register(my_tool)
        registry.register(another_tool)

        # Lookup tool
        tool = registry.get("my_tool")

        # Execute tool (sync)
        result = registry.execute("my_tool", param1="value")

        # Execute tool (async)
        result = await registry.execute_async("my_tool", param1="value")

        # Get all tools
        all_tools = registry.all()
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """
        Register a tool instance.

        Args:
            tool: Tool instance to register

        Raises:
            ValueError: If a tool with the same name is already registered
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool with name '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """
        Retrieve tool by name.

        Args:
            name: Tool name to lookup

        Returns:
            Tool instance if found, None otherwise
        """
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        """
        Get all registered tools.

        Returns:
            List of all registered tool instances
        """
        return list(self._tools.values())

    def execute(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """
        Execute a sync tool by name with parameters.

        For async tools, use execute_async() instead.

        Args:
            name: Tool name to execute
            **kwargs: Parameters to pass to tool.execute()

        Returns:
            Tool execution result dict

        Raises:
            ValueError: If tool not found (returned as error dict, not raised)
            RuntimeError: If tool is async (use execute_async instead)
        """
        tool = self.get(name)
        if tool is None:
            return {"status": "error", "error": f"Tool '{name}' not found"}
        return tool.execute(**kwargs)

    async def execute_async(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """
        Execute a tool by name with parameters (works for sync and async tools).

        Args:
            name: Tool name to execute
            **kwargs: Parameters to pass to tool.execute_async()

        Returns:
            Tool execution result dict
        """
        tool = self.get(name)
        if tool is None:
            return {"status": "error", "error": f"Tool '{name}' not found"}
        return await tool.execute_async(**kwargs)

    def __len__(self) -> int:
        """Return number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if tool is registered."""
        return name in self._tools
