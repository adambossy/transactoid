"""Phase 5 gate (Modal-independent): Fly relay pulls a real runner + resumes.

Runs the actual Phase-1 sandbox runner on uvicorn with a scripted agent, then
drives the Fly relay against it over HTTP — proving the full wire path (runner
log → codec → Fly decode → bridge translation → AI SDK frames) and the
browser-side FrameBuffer whole-turn replay, all without Modal.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest
import uvicorn
from agent_harness.core.events import InMemoryEventBus, MessageDelta, MessageEnd, MessageStart, RunEnd, RunStart
from agent_harness.core.models import Message, TextBlock, Usage

from penny.sandboxes.relay import FrameBuffer, relay_turn
from runner.server import create_app

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _msg(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)], timestamp=TS)


async def _scripted(payload: Any, bus: InMemoryEventBus) -> None:
    await bus.publish(RunStart(run_id="run", agent_name="penny", prompt=payload.prompt))
    await bus.publish(MessageStart(message_id="m1"))
    for chunk in ["Hel", "lo"]:
        await bus.publish(MessageDelta(message_id="m1", delta=chunk, partial=_msg(chunk)))
    await bus.publish(MessageEnd(message_id="m1", final=_msg("Hello"), usage=Usage(input_tokens=1)))
    await bus.publish(RunEnd(run_id="run", result=None, usage=Usage(input_tokens=1), duration_ms=1))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@contextlib.asynccontextmanager
async def _runner() -> AsyncIterator[str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(driver=_scripted), host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_relay_translates_runner_events_to_frames() -> None:
    import httpx

    async with _runner() as url:
        async with httpx.AsyncClient() as c:
            run_id = (await c.post(f"{url}/turns", json={"conversation_id": "c1", "prompt": "hi"})).json()["run_id"]

        # Relay pulls the runner and translates; also fan into a FrameBuffer.
        buf = FrameBuffer()
        types: list[str] = []
        async for frame in relay_turn(url, run_id, from_seq=0):
            types.append(frame["type"])
            await buf.append(frame)
        await buf.close()

        assert types[0] == "start"
        assert "text-delta" in types
        assert types[-1] == "finish"

        # Browser resume: replay the whole turn from the buffer.
        replay = [f["type"] async for f in buf.follow()]
        assert replay == types


@pytest.mark.asyncio
async def test_relay_text_content_roundtrips() -> None:
    import httpx

    async with _runner() as url:
        async with httpx.AsyncClient() as c:
            run_id = (await c.post(f"{url}/turns", json={"conversation_id": "c1", "prompt": "hi"})).json()["run_id"]
        text = "".join(
            f.get("delta", "") for f in [fr async for fr in relay_turn(url, run_id)] if f["type"] == "text-delta"
        )
        assert text == "Hello"
