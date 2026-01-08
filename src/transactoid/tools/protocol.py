"""Tool protocol definition for standardized tool interfaces across frontends."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class ToolParameter(TypedDict, total=False):
    """JSON Schema for a single parameter."""

    type: str
    description: str
    enum: list[str] | None
    items: dict[str, Any] | None
    properties: dict[str, Any] | None
    required: list[str] | None


class ToolInputSchema(TypedDict):
    """JSON Schema for tool input parameters."""

    type: str  # Always "object"
    properties: dict[str, ToolParameter]
    required: list[str]


@runtime_checkable
class Tool(Protocol):
    """
    Protocol for tools that can be exposed via multiple frontends.

    All tools must:
    1. Define a unique name (no spaces, lowercase_with_underscores)
    2. Provide a clear description
    3. Expose input schema as JSON Schema
    4. Implement execute() or execute_async() returning JSON-serializable dict

    Example:
        class MyTool:
            @property
            def name(self) -> str:
                return "my_tool"

            @property
            def description(self) -> str:
                return "Does something useful"

            @property
            def input_schema(self) -> ToolInputSchema:
                return {
                    "type": "object",
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "First parameter"
                        }
                    },
                    "required": ["param1"]
                }

            def execute(self, **kwargs: Any) -> dict[str, Any]:
                return {"status": "success", "result": ...}

            # For async tools:
            async def execute_async(self, **kwargs: Any) -> dict[str, Any]:
                result = await some_async_operation()
                return {"status": "success", "result": result}
    """

    @property
    def name(self) -> str:
        """Unique tool identifier (e.g., 'sync_transactions')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable tool description for LLM context."""
        ...

    @property
    def input_schema(self) -> ToolInputSchema:
        """JSON Schema defining tool parameters."""
        ...

    def is_async(self) -> bool:
        """Return True if this tool is async."""
        ...

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute tool with provided parameters (sync tools only).

        For async tools, use execute_async() instead.

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results. Should include:
            - "status": "success" or "error"
            - Additional result data or error message

        Raises:
            RuntimeError: If tool is async (use execute_async instead)
        """
        ...

    async def execute_async(self, **kwargs: Any) -> dict[str, Any]:
        """
        Execute tool with provided parameters (works for sync and async tools).

        Args:
            **kwargs: Parameters matching input_schema

        Returns:
            JSON-serializable dict with results. Should include:
            - "status": "success" or "error"
            - Additional result data or error message
        """
        ...
