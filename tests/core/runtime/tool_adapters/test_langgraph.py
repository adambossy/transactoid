from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("langchain_core", reason="langchain-core not installed")

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.core.runtime.tool_adapters.langgraph import (
    LangGraphToolAdapter,
    _build_pydantic_model,
)
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.registry import ToolRegistry


class _FakeToolNoArgs:
    @property
    def name(self) -> str:
        return "no_args_tool"

    @property
    def description(self) -> str:
        return "A tool with no arguments"

    @property
    def input_schema(self) -> ToolInputSchema:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok"}


class _FakeToolWithArgs:
    @property
    def name(self) -> str:
        return "args_tool"

    @property
    def description(self) -> str:
        return "A tool with required and optional args"

    @property
    def input_schema(self) -> ToolInputSchema:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
                "verbose": {"type": "boolean", "description": "Enable verbose"},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"results": [], "query": kwargs.get("query", "")}


def _create_adapter(
    *tools: Any,
) -> tuple[LangGraphToolAdapter, ToolRegistry]:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    invoker = SharedToolInvoker(registry)
    return LangGraphToolAdapter(registry=registry, invoker=invoker), registry


def test_langgraph_tool_adapter_no_args_tool_name_and_description() -> None:
    # input
    tool = _FakeToolNoArgs()

    # setup
    adapter, _ = _create_adapter(tool)

    # act
    output = adapter.adapt_all()

    # expected
    assert len(output) == 1
    assert output[0].name == "no_args_tool"
    assert output[0].description == "A tool with no arguments"


def test_langgraph_tool_adapter_with_args_tool_name_and_description() -> None:
    # input
    tool = _FakeToolWithArgs()

    # setup
    adapter, _ = _create_adapter(tool)

    # act
    output = adapter.adapt_all()

    # expected
    assert len(output) == 1
    assert output[0].name == "args_tool"
    assert output[0].description == "A tool with required and optional args"


def test_langgraph_tool_adapter_multiple_tools() -> None:
    # input / setup
    adapter, _ = _create_adapter(_FakeToolNoArgs(), _FakeToolWithArgs())

    # act
    output = adapter.adapt_all()

    # expected
    assert len(output) == 2
    names = {t.name for t in output}
    assert names == {"no_args_tool", "args_tool"}


def test_langgraph_tool_adapter_invokes_tool() -> None:
    # input
    tool = _FakeToolNoArgs()

    # setup
    adapter, _ = _create_adapter(tool)
    structured_tool = adapter.adapt_all()[0]

    # act — invoke the underlying coroutine
    raw_result = asyncio.run(structured_tool.arun({}))

    # expected — JSON string of the tool output
    expected_output = json.dumps({"status": "ok"})
    assert raw_result == expected_output


def test_build_pydantic_model_required_field() -> None:
    # input
    schema: ToolInputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    }

    # act
    model_class = _build_pydantic_model("test_tool", schema)
    instance = model_class(query="hello")

    # expected
    assert instance.query == "hello"


def test_build_pydantic_model_optional_field_defaults_to_none() -> None:
    # input
    schema: ToolInputSchema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Limit"}},
        "required": [],
    }

    # act
    model_class = _build_pydantic_model("test_tool", schema)
    instance = model_class()

    # expected
    assert instance.limit is None


def test_build_pydantic_model_type_mapping() -> None:
    # input
    schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "amount": {"type": "number"},
            "active": {"type": "boolean"},
            "tags": {"type": "array"},
        },
        "required": ["name", "count", "amount", "active", "tags"],
    }

    # act
    model_class = _build_pydantic_model("test_tool", schema)
    instance = model_class(
        name="foo", count=3, amount=1.5, active=True, tags=["a", "b"]
    )

    # expected
    assert instance.name == "foo"
    assert instance.count == 3
    assert instance.amount == 1.5
    assert instance.active is True
    assert instance.tags == ["a", "b"]


def test_build_pydantic_model_array_items_schema_for_primitives() -> None:
    # input
    schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "transaction_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["transaction_ids", "tags"],
    }

    # act
    model_class = _build_pydantic_model("tag_transactions", schema)
    json_schema = model_class.model_json_schema()

    # expected
    props = json_schema["properties"]
    assert props["transaction_ids"]["items"]["type"] == "integer"
    assert props["tags"]["items"]["type"] == "string"


def test_build_pydantic_model_array_items_schema_for_objects() -> None:
    # input
    schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["key", "name", "description"],
                },
            }
        },
        "required": ["targets"],
    }

    # act
    model_class = _build_pydantic_model("migrate_taxonomy", schema)
    json_schema = model_class.model_json_schema()

    # expected
    props = json_schema["properties"]
    items = props["targets"]["items"]
    assert ("$ref" in items) or (items.get("type") == "object")
