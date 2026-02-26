from __future__ import annotations

import json
from typing import Any, cast

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.registry import ToolRegistry


def _schema_type_name(spec: dict[str, Any]) -> str:
    raw_type = spec.get("type", "string")
    if isinstance(raw_type, list):
        non_null = [value for value in raw_type if value != "null"]
        if non_null:
            return str(non_null[0])
        return "string"
    return str(raw_type)


def _schema_to_annotation(
    *,
    tool_name: str,
    field_name: str,
    spec: dict[str, Any],
) -> Any:
    schema_type = _schema_type_name(spec)
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[Any]
    if schema_type == "object":
        properties = spec.get("properties")
        if not isinstance(properties, dict):
            return dict[str, Any]

        from pydantic import Field, create_model

        required_set = set(spec.get("required", []) or [])
        nested_fields: dict[str, Any] = {}
        for nested_name, nested_spec in properties.items():
            if not isinstance(nested_spec, dict):
                continue
            nested_type = _schema_to_annotation(
                tool_name=tool_name,
                field_name=f"{field_name}_{nested_name}",
                spec=nested_spec,
            )
            description = str(nested_spec.get("description", ""))
            if nested_name in required_set:
                nested_fields[nested_name] = (
                    nested_type,
                    Field(..., description=description),
                )
            else:
                nested_fields[nested_name] = (
                    nested_type | None,
                    Field(default=None, description=description),
                )

        nested_model_name = f"{tool_name}_{field_name}_Obj"
        return cast(type[Any], create_model(nested_model_name, **nested_fields))

    return str


def _build_pydantic_model(tool_name: str, schema: ToolInputSchema) -> type[Any]:
    """Build a Pydantic model from a JSON Schema dict for StructuredTool args."""
    from pydantic import Field, create_model

    properties: dict[str, Any] = schema.get("properties", {})
    required_set = set(schema.get("required", []) or [])

    fields: dict[str, Any] = {}
    for param_name, param_spec in properties.items():
        if not isinstance(param_spec, dict):
            continue
        py_type = _schema_to_annotation(
            tool_name=tool_name,
            field_name=param_name,
            spec=param_spec,
        )
        description: str = param_spec.get("description", "")
        field_kwargs: dict[str, Any] = {"description": description}
        if _schema_type_name(param_spec) == "array":
            items_spec = param_spec.get("items")
            if isinstance(items_spec, dict):
                field_kwargs["json_schema_extra"] = {"items": items_spec}
        if param_name in required_set:
            fields[param_name] = (py_type, Field(..., **field_kwargs))
        else:
            fields[param_name] = (
                py_type | None,
                Field(default=None, **field_kwargs),
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
