"""Harness session messages convert to AI SDK UIMessage JSON."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_harness.core.models import (
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)

from penny.api.hydration import messages_to_ui

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def test_messages_to_ui_round_trips_text_and_tool_calls():
    input_messages = [
        Message(role="system", content=[TextBlock(text="instructions")], timestamp=_TS),
        Message(role="user", content=[TextBlock(text="list accounts")], timestamp=_TS),
        Message(
            role="assistant",
            content=[
                ToolCallBlock(id="c1", name="list_plaid_accounts", arguments={}),
            ],
            timestamp=_TS,
        ),
        Message(
            role="tool",
            content=[ToolResultBlock(tool_call_id="c1", content='{"count": 2}')],
            timestamp=_TS,
        ),
        Message(
            role="assistant",
            content=[TextBlock(text="You have 2 accounts.")],
            timestamp=_TS,
        ),
    ]

    output = messages_to_ui(input_messages)

    expected_output = [
        {
            "id": "hist_1",
            "role": "user",
            "parts": [{"type": "text", "text": "list accounts"}],
        },
        {
            "id": "hist_2",
            "role": "assistant",
            "parts": [
                {
                    "type": "tool-list_plaid_accounts",
                    "toolCallId": "c1",
                    "state": "output-available",
                    "input": {},
                    "output": {"count": 2},
                }
            ],
        },
        {
            "id": "hist_4",
            "role": "assistant",
            "parts": [
                {"type": "text", "text": "You have 2 accounts.", "state": "done"}
            ],
        },
    ]
    assert output == expected_output
