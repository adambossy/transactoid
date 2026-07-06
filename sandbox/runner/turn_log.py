"""Per-turn, in-memory event log with sequenced replay-then-follow.

The runner subscribes to the harness ``EventBus`` and appends every event here
with a monotonically increasing ``seq``. Fly *pulls* the log over SSE with a
``from_seq`` cursor; because the whole turn is retained until it is dropped, any
number of sequential reconnections each replay from the requested offset and
then follow live — the resume contract the plan's Event-stream page describes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from protocol.events import encode_envelope


class TurnLog:
    """A single turn's ordered event log. One writer, many sequential readers."""

    def __init__(self) -> None:
        self._envelopes: list[dict[str, Any]] = []
        self._done = asyncio.Event()
        self._tick = asyncio.Condition()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def next_seq(self) -> int:
        return len(self._envelopes)

    def snapshot(self) -> list[dict[str, Any]]:
        """Every envelope appended so far — the whole turn for the finalize
        callback the runner POSTs to Fly once the turn closes."""
        return list(self._envelopes)

    async def append(self, event: Any) -> int:
        """Append one harness event; returns its assigned ``seq``."""
        async with self._tick:
            seq = len(self._envelopes)
            self._envelopes.append(encode_envelope(seq, event))
            self._tick.notify_all()
            return seq

    async def close(self) -> None:
        """Mark the turn complete; wakes followers so they can finish."""
        async with self._tick:
            self._done.set()
            self._tick.notify_all()

    async def follow(self, from_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yield envelopes from ``from_seq``, then live ones, until close."""
        cursor = max(0, from_seq)
        while True:
            async with self._tick:
                while cursor >= len(self._envelopes) and not self._done.is_set():
                    await self._tick.wait()
                batch = self._envelopes[cursor:]
                closed = self._done.is_set()
            for env in batch:
                yield env
                cursor += 1
            if closed and cursor >= len(self._envelopes):
                return
