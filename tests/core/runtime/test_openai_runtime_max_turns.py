from __future__ import annotations

import asyncio
from typing import Any

from transactoid.core.config import DEFAULT_AGENT_MAX_TURNS
from transactoid.core.runtime.openai_runtime import OpenAICoreRuntime
from transactoid.core.runtime.protocol import CoreSession, TurnCompletedEvent


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakeOpenAIStream:
    def __init__(self) -> None:
        self._events: list[object] = []

    async def stream_events(self) -> Any:
        for event in self._events:
            yield event

    def get_final_result(self) -> object:
        return type("FinalResult", (), {"final_output": "done"})()


def test_openai_runtime_streamed_uses_default_max_turns(monkeypatch: Any) -> None:
    # input
    input_text = "How much did I spend?"
    session = CoreSession(session_id="sess_1", native_session=object())

    # helper setup
    runtime: Any = object.__new__(OpenAICoreRuntime)
    runtime._agent = object()
    captured: dict[str, object] = {}

    def fake_run_streamed(
        agent: object,
        input_text: str,
        *,
        session: object,
        max_turns: int,
    ) -> _FakeOpenAIStream:
        captured["agent"] = agent
        captured["input_text"] = input_text
        captured["session"] = session
        captured["max_turns"] = max_turns
        return _FakeOpenAIStream()

    monkeypatch.setattr(
        "transactoid.core.runtime.openai_runtime.Runner.run_streamed",
        fake_run_streamed,
    )

    async def _collect() -> list[object]:
        events: list[object] = []
        async for event in runtime.run_streamed(
            input_text=input_text,
            session=session,
        ):
            events.append(event)
        return events

    # act
    output = _run_async(_collect())

    # expected
    expected_output = DEFAULT_AGENT_MAX_TURNS

    # assert
    assert captured["max_turns"] == expected_output
    assert isinstance(output[-1], TurnCompletedEvent)
