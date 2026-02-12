from __future__ import annotations

import asyncio
from typing import Any, cast

from transactoid.core.runtime.gemini_runtime import GeminiCoreRuntime
from transactoid.core.runtime.protocol import CoreSession


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakePart:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.function_call = None
        self.function_response = None


class _FakeContent:
    def __init__(self, *, parts: list[object]) -> None:
        self.parts = parts


class _FakeGeminiEvent:
    def __init__(self, *, parts: list[object], partial: bool = False) -> None:
        self.content = _FakeContent(parts=parts)
        self.partial = partial


class _FakeGeminiRunner:
    def __init__(self, *, events: list[object]) -> None:
        self._events = events

    async def run_async(self, **kwargs: object) -> Any:
        _ = kwargs
        for event in self._events:
            yield event


def test_gemini_runtime_run_concatenates_non_partial_text_chunks() -> None:
    # input
    input_text = "Generate a monthly summary"
    session = CoreSession(session_id="sess_2", native_session="sess_2")

    # helper setup
    runtime: Any = object.__new__(GeminiCoreRuntime)
    runtime._user_id = "transactoid"
    runtime._runner = _FakeGeminiRunner(
        events=[
            _FakeGeminiEvent(parts=[_FakePart(text="First sentence. ")]),
            _FakeGeminiEvent(parts=[_FakePart(text="Second sentence.")]),
        ]
    )
    runtime._build_user_message = lambda text: text

    async def _run() -> str:
        result = await cast(GeminiCoreRuntime, runtime).run(
            input_text=input_text,
            session=session,
        )
        return str(result.final_text)

    # act
    output = _run_async(_run())

    # expected
    expected_output = "First sentence. Second sentence."

    # assert
    assert output == expected_output
