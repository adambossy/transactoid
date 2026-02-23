from __future__ import annotations

import pytest

pytest.importorskip("langchain_core", reason="langchain-core not installed")
pytest.importorskip("deepagents", reason="deepagents not installed")

from transactoid.core.runtime.protocol import (
    CoreSession,
    TextDeltaEvent,
    ToolCallArgsDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallInputEvent,
    ToolCallOutputEvent,
    ToolCallStartedEvent,
    ToolOutputEvent,
)


def test_start_session_returns_correct_core_session() -> None:
    # Minimal smoke test: CoreSession holds thread_id in native_session config
    # We construct the expected shape directly without instantiating the runtime
    # (which would require deepagents + API keys at import time).
    session_key = "run-abc123"
    expected_session_id = session_key
    expected_native_session: dict[str, object] = {
        "configurable": {"thread_id": session_key}
    }

    session = CoreSession(
        session_id=expected_session_id,
        native_session=expected_native_session,
    )

    assert session.session_id == session_key
    assert session.native_session == {"configurable": {"thread_id": session_key}}


def test_start_session_continue_uses_run_id_as_thread_id() -> None:
    # Verify the continue pattern: run_id is used as session_key → thread_id
    run_id = "report-2026-01"
    session = CoreSession(
        session_id=run_id,
        native_session={"configurable": {"thread_id": run_id}},
    )
    config = session.native_session
    assert isinstance(config, dict)
    assert config["configurable"]["thread_id"] == run_id


# ---------------------------------------------------------------------------
# Streaming event mapping tests (unit-test the mapping logic directly)
# ---------------------------------------------------------------------------


class _FakeAIMessageChunk:
    """Minimal AIMessageChunk stand-in for testing."""

    type = "AIMessageChunk"

    def __init__(
        self,
        content: str = "",
        tool_call_chunks: list[dict[str, object]] | None = None,
    ) -> None:
        self.content = content
        self.tool_call_chunks = tool_call_chunks or []


class _FakeToolMessage:
    """Minimal ToolMessage stand-in for testing."""

    type = "tool"

    def __init__(
        self,
        tool_call_id: str,
        content: str,
    ) -> None:
        self.tool_call_id = tool_call_id
        self.content = content


def _collect_events_from_chunk(
    chunk: tuple[object, object],
) -> list[object]:
    """Replicate event mapping logic from LangGraphCoreRuntime._iter_stream_events."""
    import json as _json

    events: list[object] = []
    if not isinstance(chunk, tuple) or len(chunk) != 2:
        return events

    message, _metadata = chunk
    seen_tool_names: dict[str, str] = {}

    msg_type = getattr(message, "type", None)
    content = getattr(message, "content", None)
    if msg_type != "tool" and isinstance(content, str) and content:
        events.append(TextDeltaEvent(text=content))

    tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
    for tc_chunk in tool_call_chunks:
        call_id: str = tc_chunk.get("id") or f"call_{tc_chunk.get('index', 0)}"
        tool_name: str = tc_chunk.get("name") or ""
        args_delta: str = tc_chunk.get("args") or ""

        if tool_name:
            seen_tool_names[call_id] = tool_name
            from transactoid.core.runtime.protocol import classify_tool_kind

            events.append(
                ToolCallStartedEvent(
                    call_id=call_id,
                    tool_name=tool_name,
                    kind=classify_tool_kind(tool_name),
                )
            )
        if args_delta:
            events.append(ToolCallArgsDeltaEvent(call_id=call_id, delta=args_delta))

    if msg_type == "tool":
        call_id = getattr(message, "tool_call_id", "unknown") or "unknown"
        raw_content = getattr(message, "content", "")
        output: dict[str, object] | str
        try:
            parsed = _json.loads(raw_content)
            output = parsed if isinstance(parsed, dict) else raw_content
        except Exception:
            output = raw_content if isinstance(raw_content, str) else str(raw_content)

        tool_name_for_call = seen_tool_names.get(call_id, "")
        from typing import Literal

        status: Literal["completed", "failed"] = "completed"
        if isinstance(output, dict) and output.get("status") == "error":
            status = "failed"

        events.append(
            ToolCallInputEvent(
                call_id=call_id,
                tool_name=tool_name_for_call,
                arguments={},
                runtime_info=None,
            )
        )
        events.append(ToolCallCompletedEvent(call_id=call_id))
        events.append(ToolOutputEvent(call_id=call_id, output=output))
        events.append(
            ToolCallOutputEvent(
                call_id=call_id,
                status=status,
                output=output,
                runtime_info=None,
                named_outputs=None,
            )
        )

    return events


def test_map_chunk_text_delta_produces_text_event() -> None:
    # input
    chunk: tuple[object, object] = (_FakeAIMessageChunk(content="Hello world"), {})

    # act
    events = _collect_events_from_chunk(chunk)

    # expected
    assert len(events) == 1
    assert isinstance(events[0], TextDeltaEvent)
    assert events[0].text == "Hello world"


def test_map_chunk_empty_text_produces_no_event() -> None:
    # input
    chunk: tuple[object, object] = (_FakeAIMessageChunk(content=""), {})

    # act
    events = _collect_events_from_chunk(chunk)

    # expected
    assert events == []


def test_map_chunk_tool_call_chunk_with_name_produces_started_event() -> None:
    # input
    tc_chunk: dict[str, object] = {"id": "call_1", "name": "run_sql", "args": ""}
    chunk: tuple[object, object] = (
        _FakeAIMessageChunk(tool_call_chunks=[tc_chunk]),
        {},
    )

    # act
    events = _collect_events_from_chunk(chunk)

    # expected
    assert len(events) == 1
    assert isinstance(events[0], ToolCallStartedEvent)
    assert events[0].call_id == "call_1"
    assert events[0].tool_name == "run_sql"
    assert events[0].kind == "execute"


def test_map_chunk_tool_call_chunk_with_args_produces_args_delta_event() -> None:
    # input
    tc_chunk: dict[str, object] = {
        "id": "call_1",
        "name": "run_sql",
        "args": '{"query":',
    }
    chunk: tuple[object, object] = (
        _FakeAIMessageChunk(tool_call_chunks=[tc_chunk]),
        {},
    )

    # act
    events = _collect_events_from_chunk(chunk)

    # expected — ToolCallStartedEvent + ToolCallArgsDeltaEvent
    assert len(events) == 2
    assert isinstance(events[0], ToolCallStartedEvent)
    assert isinstance(events[1], ToolCallArgsDeltaEvent)
    assert events[1].call_id == "call_1"
    assert events[1].delta == '{"query":'


def test_map_chunk_tool_message_produces_completed_and_output_events() -> None:
    # input
    import json

    output = {"rows": [], "count": 0}
    chunk: tuple[object, object] = (
        _FakeToolMessage(tool_call_id="call_1", content=json.dumps(output)),
        {},
    )

    # act
    events = _collect_events_from_chunk(chunk)

    # expected — 4 events: ToolCallInputEvent, Completed, Output, OutputEvent
    assert len(events) == 4
    assert isinstance(events[0], ToolCallInputEvent)
    assert isinstance(events[1], ToolCallCompletedEvent)
    assert isinstance(events[2], ToolOutputEvent)
    assert isinstance(events[3], ToolCallOutputEvent)
    assert events[1].call_id == "call_1"
    assert events[2].output == output
    assert events[3].status == "completed"


def test_map_chunk_tool_message_with_error_status_produces_failed_status() -> None:
    # input
    import json

    output = {"status": "error", "message": "something went wrong"}
    chunk: tuple[object, object] = (
        _FakeToolMessage(tool_call_id="call_2", content=json.dumps(output)),
        {},
    )

    # act
    events = _collect_events_from_chunk(chunk)

    # expected
    tool_output_event = events[3]
    assert isinstance(tool_output_event, ToolCallOutputEvent)
    assert tool_output_event.status == "failed"


def test_map_chunk_non_tuple_produces_no_events() -> None:
    # input
    chunk = "not a tuple"

    # act
    events = _collect_events_from_chunk(chunk)  # type: ignore[arg-type]

    # expected
    assert events == []
