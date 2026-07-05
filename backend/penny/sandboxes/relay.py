"""The Fly relay: pull the runner's event log, translate to AI SDK frames.

Fly *pulls* SSE from the sandbox runner over the Modal tunnel with a ``from_seq``
cursor, decodes each wire envelope back into a harness event, and runs it through
the existing ``bridge._translate`` — so the browser sees exactly the frames it
does today. A per-run :class:`FrameBuffer` retains the translated frames for the
in-flight turn so a reconnecting browser replays the whole turn then follows live
(whole-turn replay). A dropped Fly pull re-GETs from ``from_seq=0``; translation
is idempotent because the browser buffer is rebuilt from a full replay.

The one shared seam: this website-domain module imports ``protocol`` (the wire
codec) — the allowed backend→protocol dependency — plus ``bridge`` (its peer).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from protocol.events import decode_envelope

from penny.api.bridge import _translate


async def relay_turn(
    tunnel_url: str, run_id: str, *, from_seq: int = 0, client: httpx.AsyncClient | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Pull the runner's events and yield translated AI SDK frames."""
    import json

    owns = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))
    open_text: set[str] = set()
    url = f"{tunnel_url.rstrip('/')}/runs/{run_id}/events"
    try:
        async with http.stream("GET", url, params={"from_seq": from_seq}) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                body = line[len("data: ") :]
                if body.strip() == "[DONE]":
                    return
                _seq, event = decode_envelope(json.loads(body))
                try:
                    frames = _translate(event, open_text)
                except Exception as exc:  # a translation bug is a frame, not a hang
                    frames = [{"type": "error", "errorText": f"stream translation failed: {exc}"}]
                for frame in frames:
                    yield frame
    finally:
        if owns:
            await http.aclose()


class FrameBuffer:
    """Per-run ordered AI SDK frame buffer with replay-then-follow.

    Enables browser-side whole-turn resume: a reconnecting client replays every
    buffered frame, then follows live until the run finalizes.
    """

    def __init__(self) -> None:
        self._frames: list[dict[str, Any]] = []
        self._done = asyncio.Event()
        self._tick = asyncio.Condition()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    async def append(self, frame: dict[str, Any]) -> None:
        async with self._tick:
            self._frames.append(frame)
            self._tick.notify_all()

    async def close(self) -> None:
        async with self._tick:
            self._done.set()
            self._tick.notify_all()

    async def follow(self) -> AsyncIterator[dict[str, Any]]:
        cursor = 0
        while True:
            async with self._tick:
                while cursor >= len(self._frames) and not self._done.is_set():
                    await self._tick.wait()
                batch = self._frames[cursor:]
                closed = self._done.is_set()
            for frame in batch:
                yield frame
                cursor += 1
            if closed and cursor >= len(self._frames):
                return
