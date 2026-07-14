"""Fly-side orchestration of a sandboxed chat turn (Phase 5 integration seam).

Ties the pieces together for one turn behind the ``PENNY_SANDBOX_TURNS`` flag:

1. dispatch a sandbox for the conversation (warm reuse / restore / cold create),
2. build the ``TurnPayload`` — render the system prompt on Fly, seed prior
   messages, mint the MCP capability token, point the model at the proxy,
3. ``POST /turns`` to the runner, then relay its events, translating to AI SDK
   frames, persisting the assistant turn, and buffering frames for browser resume,
4. on ``RunEnd`` (or a clean cancel) return the conversation to IDLE.

This is the website-domain counterpart to ``bridge.stream_and_persist``: same
role, but the loop runs in the sandbox and Fly relays it. Live end-to-end wiring
into ``api/main.py`` is the final integration step; the orchestration itself is
here and unit-covered piecewise (dispatch/reaper, relay, codec).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any

import httpx
from loguru import logger

from .provider import SandboxProvider
from .reaper import dispatch_turn, on_turn_end
from .relay import FrameBuffer, relay_turn
from .store import ConversationSandbox


def _sse(frame: dict[str, Any]) -> str:
    return f"data: {json.dumps(frame, default=str)}\n\n"


async def stream_sandboxed_turn(
    *,
    rec: ConversationSandbox,
    provider: SandboxProvider,
    payload: dict[str, Any],
    now: float,
    frame_buffer: FrameBuffer | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[str]:
    """Dispatch a sandbox, run the turn, relay+persist, and finalize.

    ``payload`` is a fully-built ``TurnPayload`` dict (system prompt already
    rendered on Fly, tokens minted). Yields AI SDK SSE frames for the browser.
    """
    owns = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))
    try:
        handle = await dispatch_turn(rec, provider, now=now)
        payload["conversation_id"] = rec.conversation_id
        start = await http.post(f"{handle.tunnel_url.rstrip('/')}/turns", json=payload)
        start.raise_for_status()
        run_id = start.json()["run_id"]

        async for frame in relay_turn(
            handle.tunnel_url, run_id, from_seq=0, client=http
        ):
            if frame_buffer is not None:
                await frame_buffer.append(frame)
            yield _sse(frame)
    except Exception as exc:  # surface a loop/transport failure as an error frame
        logger.bind(conversation_id=rec.conversation_id).warning(
            "sandboxed turn failed: {}", exc
        )
        yield _sse({"type": "error", "errorText": str(exc)})
    finally:
        if frame_buffer is not None:
            await frame_buffer.close()
        await on_turn_end(rec, now=now)
        if owns:
            await http.aclose()
    yield "data: [DONE]\n\n"


async def cancel_turn(
    rec: ConversationSandbox, run_id: str, *, client: httpx.AsyncClient | None = None
) -> None:
    """Route a browser stop to the runner's cancel endpoint."""
    if rec.tunnel_url is None:
        return
    owns = client is None
    http = client or httpx.AsyncClient(timeout=30.0)
    try:
        await http.post(f"{rec.tunnel_url.rstrip('/')}/runs/{run_id}/cancel")
    finally:
        if owns:
            await http.aclose()
