from __future__ import annotations

from typing import Any

from transactoid.tools.registry import ToolRegistry


class SharedToolInvoker:
    """Single shared tool invocation path used by all runtime providers."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def invoke(self, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Invoke a registered tool by name and return JSON-serializable output."""
        return await self._registry.execute(tool_name, **args)
