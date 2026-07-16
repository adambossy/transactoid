"""The event codec round-trips every wire-relevant harness event by value.

This is the plan's Event-stream verification at the unit level: a harness event
encoded on the runner and decoded on the relay must reconstruct an *equal*
object, so the existing ``penny.api.bridge._translate`` sees exactly what it
does today. The two documented special cases (``RunEnd.result`` dropped,
``Error.cause`` a type) are asserted explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from agent_harness.core.events import (
    Error,
    MessageDelta,
    MessageEnd,
    ModelUsage,
    RunEnd,
    RunStart,
    ThinkingDelta,
    ToolCallEnd,
    ToolExecEnd,
)
from agent_harness.core.models import Cost, Message, TextBlock, Usage
from agent_harness.core.tools import ToolResult

from protocol.events import decode_event, encode_event

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _msg(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)], timestamp=TS)


def _roundtrip(event: object) -> object:
    return decode_event(encode_event(event))


@pytest.mark.parametrize(
    "event",
    [
        RunStart(run_id="r1", agent_name="penny", prompt="hi"),
        ThinkingDelta(message_id="m1", delta="think", partial="think"),
        MessageDelta(message_id="m1", delta="he", partial=_msg("he")),
        MessageEnd(message_id="m1", final=_msg("hello"), usage=Usage(input_tokens=3)),
        ToolCallEnd(tool_call_id="t1", tool_name="run_sql", arguments={"q": "select 1"}),
        ModelUsage(model_name="g", usage=Usage(input_tokens=1), cost=Cost(input_cost=0.01)),
    ],
)
def test_value_events_roundtrip_equal(event: object) -> None:
    assert _roundtrip(event) == event


def test_tool_exec_end_roundtrips_result() -> None:
    result = ToolResult(
        content=[TextBlock(text="ok")],
        structured_content={"rows": [{"n": 1}]},
        metadata={"source": "run_sql"},
    )
    event = ToolExecEnd(tool_call_id="t1", result=result)
    back = _roundtrip(event)
    assert back.tool_call_id == "t1"
    assert back.result.structured_content == {"rows": [{"n": 1}]}
    assert back.result.content[0].text == "ok"
    assert back.error is None


def test_run_end_drops_result_but_keeps_usage() -> None:
    event = RunEnd(run_id="r1", result={"not": "serializable-layer3"}, usage=Usage(input_tokens=5), duration_ms=42)
    back = _roundtrip(event)
    assert back.result is None  # Layer-3 result never rides the wire
    assert back.usage == Usage(input_tokens=5)
    assert back.duration_ms == 42


def test_error_cause_roundtrips_as_type() -> None:
    event = Error(message="boom", cause=ValueError, recoverable=True)
    back = _roundtrip(event)
    assert back.message == "boom"
    assert back.cause is ValueError
    assert back.recoverable is True
