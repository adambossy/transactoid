from __future__ import annotations

import json
from typing import Any, cast

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.registry import ToolRegistry


def _build_pydantic_model(tool_name: str, schema: ToolInputSchema) -> type[Any]:
    """Build a Pydantic model from a JSON Schema dict for StructuredTool args."""
    from pydantic import Field, create_model

    properties: dict[str, Any] = schema.get("properties", {})
    required_set = set(schema.get("required", []) or [])

    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
    }

    fields: dict[str, Any] = {}
    for param_name, param_spec in properties.items():
        raw_type = param_spec.get("type", "string")
        py_type: type = type_map.get(raw_type, str)
        description: str = param_spec.get("description", "")
        if param_name in required_set:
            fields[param_name] = (py_type, Field(description=description))
        else:
            fields[param_name] = (
                py_type | None,
                Field(default=None, description=description),
            )

    model_name = f"{tool_name}_Args"
    return cast(type[Any], create_model(model_name, **fields))


class LangGraphToolAdapter:
    """Adapt shared ToolRegistry tools to LangChain StructuredTool objects."""

    def __init__(self, *, registry: ToolRegistry, invoker: SharedToolInvoker) -> None:
        self._registry = registry
        self._invoker = invoker

    def adapt_all(self) -> list[Any]:
        """Return all registered tools as LangChain StructuredTool objects."""
        return [self._adapt_one(tool.name) for tool in self._registry.all()]

    def _adapt_one(self, tool_name: str) -> Any:
        from langchain_core.tools import StructuredTool

        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found in registry: {tool_name}")

        schema = tool.input_schema
        invoker = self._invoker

        async def tool_func(**kwargs: Any) -> str:
            result = await invoker.invoke(tool_name=tool_name, args=kwargs)
            return json.dumps(result)

        properties: dict[str, Any] = schema.get("properties", {})
        if properties:
            args_schema = _build_pydantic_model(tool.name, schema)
            return StructuredTool.from_function(
                coroutine=tool_func,
                name=tool.name,
                description=tool.description,
                args_schema=args_schema,
            )
        else:
            return StructuredTool.from_function(
                coroutine=tool_func,
                name=tool.name,
                description=tool.description,
            )
