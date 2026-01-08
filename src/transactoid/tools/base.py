"""Base implementation for tools implementing the Tool protocol."""

from __future__ import annotations

import inspect
from typing import Any

from transactoid.tools.protocol import ToolInputSchema


class StandardTool:
    """
    Base class providing common Tool protocol implementation.

    Subclasses must override:
    - _name: Tool name
    - _description: Tool description
    - _input_schema: Parameter schema
    - _execute_impl: Core execution logic (sync or async)

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

            def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
                param = kwargs["param"]
                return {"status": "success", "result": f"Got {param}"}

        # Async tools are also supported:
        class MyAsyncTool(StandardTool):
            async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
                result = await some_async_operation()
                return {"status": "success", "result": result}
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

    def is_async(self) -> bool:
        """Return True if this tool's _execute_impl is async."""
        return inspect.iscoroutinefunction(self._execute_impl)

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """
        Validate and execute tool logic (sync tools only).

        For async tools, use execute_async() instead.

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results

        Raises:
            RuntimeError: If called on an async tool
        """
        if self.is_async():
            raise RuntimeError(
                f"{self.__class__.__name__} is async. Use execute_async() instead."
            )
        result = self._execute_impl(**kwargs)
        # Type narrowing: we know it's not a coroutine since is_async() is False
        return result

    async def execute_async(self, **kwargs: Any) -> dict[str, Any]:
        """
        Validate and execute tool logic (works for both sync and async tools).

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results
        """
        result = self._execute_impl(**kwargs)
        if inspect.iscoroutine(result):
            return await result
        return result

    def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        """
        Override in subclass to implement tool logic.

        Can be either sync or async.

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
