"""Golden test for the runner server: streaming, resume, and cancel.

Drives a scripted fake agent (no model, no MCP) through the real FastAPI app so
the turn log, the resumable SSE endpoint, and the cancel path are exercised
end to end in-process.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from agent_harness.core.events import InMemoryEventBus, MessageDelta, MessageEnd, MessageStart, RunEnd, RunStart
from agent_harness.core.models import Message, TextBlock, Usage

from protocol.events import decode_envelope
from runner.server import create_app

TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _msg(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)], timestamp=TS)


async def _scripted_driver(payload, bus: InMemoryEventBus) -> None:
    """Publish a small deterministic event sequence, honoring cancellation."""
    await bus.publish(RunStart(run_id="run", agent_name="penny", prompt=payload.prompt))
    await bus.publish(MessageStart(message_id="m1"))
    for i, chunk in enumerate(["Hel", "lo ", "wor", "ld"]):
        await bus.publish(MessageDelta(message_id="m1", delta=chunk, partial=_msg(chunk)))
        await asyncio.sleep(0.05)  # a window for a mid-run cancel
    await bus.publish(MessageEnd(message_id="m1", final=_msg("Hello world"), usage=Usage(input_tokens=1)))
    await bus.publish(RunEnd(run_id="run", result=None, usage=Usage(input_tokens=1), duration_ms=1))


def _types(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        if not ln.startswith("data: "):
            continue
        body = ln[len("data: ") :]
        if body.strip() == "[DONE]":
            out.append("[DONE]")
            continue
        _seq, event = decode_envelope(json.loads(body))
        out.append(type(event).__name__)
    return out


async def _collect(client: httpx.AsyncClient, run_id: str, from_seq: int = 0) -> list[str]:
    lines: list[str] = []
    async with client.stream("GET", f"/runs/{run_id}/events?from_seq={from_seq}") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                lines.append(line)
    return lines


@pytest.mark.asyncio
async def test_happy_path_and_resume() -> None:
    app = create_app(driver=_scripted_driver)
    if True:  # ASGITransport needs no lifespan for these endpoints
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
            r = await client.post("/turns", json={"conversation_id": "c1", "prompt": "hi"})
            assert r.status_code == 200
            run_id = r.json()["run_id"]

            # Full stream from seq 0.
            first = _types(await _collect(client, run_id, from_seq=0))
            assert first[0] == "RunStart"
            assert "MessageDelta" in first
            assert first[-2] == "RunEnd"
            assert first[-1] == "[DONE]"

            # Resume: a second reader replays the whole (now finished) turn.
            again = _types(await _collect(client, run_id, from_seq=0))
            assert again == first

            # from_seq offset skips already-seen events.
            tail = _types(await _collect(client, run_id, from_seq=first.index("RunEnd")))
            assert tail[0] == "RunEnd"


@pytest.mark.asyncio
async def test_second_concurrent_turn_conflicts() -> None:
    started = asyncio.Event()

    async def _blocking_driver(payload, bus: InMemoryEventBus) -> None:
        await bus.publish(RunStart(run_id="run", agent_name="penny", prompt=payload.prompt))
        started.set()
        await asyncio.sleep(1.0)
        await bus.publish(RunEnd(run_id="run", result=None, usage=Usage(), duration_ms=1))

    app = create_app(driver=_blocking_driver)
    if True:  # ASGITransport needs no lifespan for these endpoints
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
            r1 = await client.post("/turns", json={"conversation_id": "c1", "prompt": "one"})
            assert r1.status_code == 200
            await asyncio.wait_for(started.wait(), timeout=2)
            r2 = await client.post("/turns", json={"conversation_id": "c1", "prompt": "two"})
            assert r2.status_code == 409


@pytest.mark.asyncio
async def test_cancel_mid_run_closes_cleanly() -> None:
    app = create_app(driver=_scripted_driver)
    if True:  # ASGITransport needs no lifespan for these endpoints
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
            run_id = (await client.post("/turns", json={"conversation_id": "c1", "prompt": "hi"})).json()["run_id"]
            await asyncio.sleep(0.08)  # let a couple of deltas land
            c = await client.post(f"/runs/{run_id}/cancel")
            assert c.status_code == 200 and c.json()["cancelled"] is True

            # The stream closes cleanly with a terminal Error, not a hang.
            types = _types(await _collect(client, run_id, from_seq=0))
            assert types[0] == "RunStart"
            assert types[-2] == "Error"  # "run cancelled" terminal event
            assert types[-1] == "[DONE]"
            # It stopped early — a full run would end in RunEnd, not here.
            assert "RunEnd" not in types
