from __future__ import annotations

from decimal import Decimal
from typing import Any

from transactoid.tools.registry import ToolRegistry


def _normalize_json_value(value: Any) -> Any:
    """Normalize tool output values into JSON-serializable primitives."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    return value


class SharedToolInvoker:
    """Single shared tool invocation path used by all runtime providers."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def invoke(self, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Invoke a registered tool by name and return JSON-serializable output."""
        result = await self._registry.execute(tool_name, **args)
        normalized_result = _normalize_json_value(result)
        if not isinstance(normalized_result, dict):
            raise TypeError(
                f"Tool '{tool_name}' returned non-dict result; got "
                f"{type(normalized_result).__name__}"
            )
        return normalized_result
