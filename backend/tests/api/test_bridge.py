"""Unit tests for the harness-event → AI SDK frame translation."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_harness.core.events import (
    Error,
    MessageDelta,
    MessageEnd,
    RunEnd,
    RunStart,
    ToolCallEnd,
    ToolExecEnd,
)
from agent_harness.core.models import Message, TextBlock, Usage
from agent_harness.core.tools import ToolResult

from penny.api.bridge import _serialize_tool_output, _translate


def _assistant_partial(text: str) -> Message:
    return Message(
        role="assistant",
        content=[TextBlock(text=text)],
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_translate_run_start_emits_start_and_step():
    input_event = RunStart(run_id="run_1", agent_name="penny", prompt="hi")

    output = _translate(input_event, set())

    expected_output = [
        {"type": "start", "messageId": "run_1"},
        {"type": "start-step"},
    ]
    assert output == expected_output


def test_translate_message_delta_opens_text_part_once():
    open_text: set[str] = set()
    first = MessageDelta(message_id="m1", delta="he", partial=_assistant_partial("he"))
    second = MessageDelta(
        message_id="m1", delta="llo", partial=_assistant_partial("hello")
    )

    output_first = _translate(first, open_text)
    output_second = _translate(second, open_text)

    assert output_first == [
        {"type": "text-start", "id": "t_m1"},
        {"type": "text-delta", "id": "t_m1", "delta": "he"},
    ]
    assert output_second == [{"type": "text-delta", "id": "t_m1", "delta": "llo"}]


def test_translate_message_end_closes_open_text_part():
    open_text = {"t_m1"}
    input_event = MessageEnd(
        message_id="m1", final=_assistant_partial("hello"), usage=Usage()
    )

    output = _translate(input_event, open_text)

    assert output == [{"type": "text-end", "id": "t_m1"}]
    assert open_text == set()


def test_translate_tool_call_end_emits_input_available():
    input_event = ToolCallEnd(
        tool_call_id="c1", tool_name="run_sql", arguments={"query": "SELECT 1"}
    )

    output = _translate(input_event, set())

    expected_output = [
        {
            "type": "tool-input-available",
            "toolCallId": "c1",
            "toolName": "run_sql",
            "input": {"query": "SELECT 1"},
        }
    ]
    assert output == expected_output


def test_translate_tool_exec_end_success_emits_structured_output():
    result = ToolResult(
        content=[TextBlock(text='{"count": 6}')],
        structured_content={"count": 6},
    )
    input_event = ToolExecEnd(tool_call_id="c1", result=result)

    output = _translate(input_event, set())

    expected_output = [
        {
            "type": "tool-output-available",
            "toolCallId": "c1",
            "output": {"count": 6},
        }
    ]
    assert output == expected_output


def test_translate_tool_exec_end_error_emits_tool_output_error():
    result = ToolResult(content=[TextBlock(text="boom")], error="boom")
    input_event = ToolExecEnd(tool_call_id="c1", result=result)

    output = _translate(input_event, set())

    expected_output = [
        {"type": "tool-output-error", "toolCallId": "c1", "errorText": "boom"}
    ]
    assert output == expected_output


def test_translate_run_end_emits_finish_frames():
    input_event = RunEnd(run_id="run_1", result=None, usage=Usage(), duration_ms=5)

    output = _translate(input_event, set())

    assert output == [{"type": "finish-step"}, {"type": "finish"}]


def test_translate_error_emits_error_frame():
    input_event = Error(message="quota exceeded")

    output = _translate(input_event, set())

    assert output == [{"type": "error", "errorText": "quota exceeded"}]


def test_serialize_tool_output_prefers_structured_content():
    input_result = ToolResult(
        content=[TextBlock(text='{"items": []}')],
        structured_content={"items": []},
    )

    output = _serialize_tool_output(input_result)

    assert output == {"items": []}


def test_serialize_tool_output_falls_back_to_content_envelope():
    input_result = ToolResult(content=[TextBlock(text="plain string result")])

    output = _serialize_tool_output(input_result)

    expected_output = {
        "content": [{"type": "text", "text": "plain string result"}],
        "error": None,
        "metadata": {},
    }
    assert output == expected_output
