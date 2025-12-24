"""Base implementation for tools implementing the Tool protocol."""

from __future__ import annotations

from typing import Any

from tools.protocol import ToolInputSchema


class StandardTool:
    """
    Base class providing common Tool protocol implementation.

    Subclasses must override:
    - _name: Tool name
    - _description: Tool description
    - _input_schema: Parameter schema
    - _execute_impl: Core execution logic

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

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """
        Validate and execute tool logic.

        Override _execute_impl in subclasses to implement custom logic.

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results
        """
        # Could add validation here if needed
        return self._execute_impl(**kwargs)

    def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
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
