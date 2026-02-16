from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.registry import ToolRegistry


class _DecimalTool:
    @property
    def name(self) -> str:
        return "decimal_tool"

    @property
    def description(self) -> str:
        return "Returns nested Decimal values"

    @property
    def input_schema(self) -> ToolInputSchema:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "rows": [
                {"amount": Decimal("1522.0000000000000000"), "id": 1},
                {"amount": Decimal("42.99"), "id": 2},
            ],
            "summary": {
                "total": Decimal("1564.99"),
                "parts": (Decimal("1.23"), Decimal("4.56")),
            },
        }


def test_shared_tool_invoker_normalizes_nested_decimals() -> None:
    # input
    tool_name = "decimal_tool"
    args: dict[str, Any] = {}

    # helper setup
    registry = ToolRegistry()
    registry.register(_DecimalTool())
    invoker = SharedToolInvoker(registry)

    # act
    output = asyncio.run(
        invoker.invoke(
            tool_name=tool_name,
            args=args,
        )
    )

    # expected
    expected_output = {
        "rows": [
            {"amount": 1522.0, "id": 1},
            {"amount": 42.99, "id": 2},
        ],
        "summary": {
            "total": 1564.99,
            "parts": [1.23, 4.56],
        },
    }

    # assert
    assert output == expected_output
