"""Base implementation for tools implementing the Tool protocol."""

from __future__ import annotations

from typing import Any

from transactoid.tools.protocol import ToolInputSchema


class StandardTool:
    """
    Base class providing common Tool protocol implementation.

    Subclasses must override:
    - _name: Tool name
    - _description: Tool description
    - _input_schema: Parameter schema
    - _execute_impl: Core execution logic (async)

    Example:
        class MyTool(StandardTool):
            _name = "my_tool"
            _description = "Does something useful"
            _input_schema: ToolInputSchema = {
                "type": "object",
                "properties": {
                    "param": {"type": "string", "description": "A parameter"}
                },
                "required": ["param"]
            }

            async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
                result = await some_async_operation()
                return {"status": "success", "result": result}

        # Tools without async operations can simply not use await:
        class SimpleTool(StandardTool):
            async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
                return {"status": "success", "result": 2 + 2}
    """

    _name: str
    _description: str
    _input_schema: ToolInputSchema

    @property
    def name(self) -> str:
        """Return the tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Return the tool description."""
        return self._description

    @property
    def input_schema(self) -> ToolInputSchema:
        """Return the input schema."""
        return self._input_schema

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """
        Validate and execute tool logic.

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results
        """
        return await self._execute_impl(**kwargs)

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Override in subclass to implement tool logic.

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _execute_impl"
        )
