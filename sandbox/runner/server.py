"""The runner: a tunnel-exposed HTTP server that runs one turn at a time.

Endpoints (all consumed by the Fly relay, never the browser):

* ``POST /turns`` — start a run; returns ``{run_id}``. One active run per
  sandbox; a second concurrent turn gets ``409``.
* ``GET /runs/{run_id}/events?from_seq=N`` — SSE of ``{seq, event}`` envelopes
  from N, then live until the turn closes. Reconnectable any number of times.
* ``POST /runs/{run_id}/cancel`` — abort the in-flight run; the browser stop
  button routes here. Flushes a terminal event so a reader still sees a clean
  close.
* ``GET /healthz`` — readiness-probe target.

A run executes in a detached task that publishes to an ``InMemoryEventBus``; a
drain task folds every event into the turn's :class:`TurnLog`. The agent factory
is injectable so tests can drive a scripted fake without a model or MCP server.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
import json
import traceback
from typing import Any
import uuid

from agent_harness import Agent
from agent_harness.core.events import Error, InMemoryEventBus
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from protocol.turn import TurnPayload

from .agent_assembly import build_agent
from .turn_log import TurnLog

# A run driver: given the payload and a bus, run the agent to completion. The
# default builds the real agent; tests inject a scripted fake.
RunDriver = Callable[[TurnPayload, InMemoryEventBus], Awaitable[None]]


async def _default_driver(payload: TurnPayload, bus: InMemoryEventBus) -> None:
    agent: Agent = await build_agent(payload)
    await agent.run(prompt=payload.prompt, event_bus=bus)


def _format_exc(exc: BaseException) -> str:
    """Flatten an exception, unwrapping ``ExceptionGroup`` (agent-harness runs the
    loop in a TaskGroup, so a failure arrives as a group whose ``str`` is the
    useless "unhandled errors in a TaskGroup"). Return the real leaf messages.
    """
    parts: list[str] = []

    def walk(e: BaseException, depth: int) -> None:
        parts.append(f"{'  ' * depth}{type(e).__name__}: {e}")
        subs = getattr(e, "exceptions", None)  # ExceptionGroup
        if subs:
            for s in subs:
                walk(s, depth + 1)
        elif e.__cause__ is not None:
            walk(e.__cause__, depth + 1)

    walk(exc, 0)
    return " | ".join(parts)


@dataclass
class _Run:
    run_id: str
    log: TurnLog
    drive_task: asyncio.Task[None] | None = None
    agent_task: asyncio.Task[None] | None = None
    cancelled: bool = False


def create_app(driver: RunDriver = _default_driver) -> FastAPI:
    app = FastAPI(title="penny-sandbox-runner")
    # One sandbox == one conversation == at most one active run. ``runs`` retains
    # the current/last run so a finished turn is still replayable (resume within
    # the grace window); ``active`` is the in-flight one, if any.
    runs: dict[str, _Run] = {}
    state: dict[str, _Run | None] = {"active": None}

    async def _drive(payload: TurnPayload, run: _Run) -> None:
        bus = InMemoryEventBus()
        subscription = bus.subscribe()

        async def _run_agent() -> None:
            try:
                await driver(payload, bus)
            except asyncio.CancelledError:
                pass  # cancel() aborts the agent; the bus close below ends drain
            except BaseException as exc:  # noqa: BLE001 - a loop failure surfaces as a wire event
                # Log the full traceback to the sandbox's stdout for post-mortem,
                # and put the UNWRAPPED exception on the wire so the real cause
                # (not "unhandled errors in a TaskGroup") reaches Fly + Langfuse.
                print(
                    f"[runner] agent run failed:\n{traceback.format_exc()}", flush=True
                )
                await run.log.append(Error(message=_format_exc(exc)))
            finally:
                await bus.close()

        run.agent_task = asyncio.create_task(_run_agent())
        # Drain every event into the log; ends when the bus closes.
        async for event in subscription:
            await run.log.append(event)
        await run.agent_task  # already finishing; ensures its finally ran
        if run.cancelled:
            await run.log.append(Error(message="run cancelled", recoverable=False))
        await run.log.close()
        state["active"] = None  # run stays in ``runs`` for replay

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/turns")
    async def start_turn(payload: TurnPayload) -> JSONResponse:
        active = state["active"]
        if active is not None and not active.log.done:
            raise HTTPException(status_code=409, detail="a run is already active")
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = _Run(run_id=run_id, log=TurnLog())
        runs.clear()  # one conversation per sandbox: retain only the current run
        runs[run_id] = run
        run.drive_task = asyncio.create_task(_drive(payload, run))
        state["active"] = run
        return JSONResponse({"run_id": run_id})

    def _lookup(run_id: str) -> _Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return run

    @app.get("/runs/{run_id}/events")
    async def events(
        run_id: str, request: Request, from_seq: int = 0
    ) -> StreamingResponse:
        run = _lookup(run_id)

        async def _sse() -> AsyncIterator[str]:
            async for env in run.log.follow(from_seq=from_seq):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(env)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
            },
        )

    @app.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str) -> dict[str, Any]:
        run = _lookup(run_id)
        run.cancelled = True
        if run.agent_task is not None and not run.agent_task.done():
            run.agent_task.cancel()
        if run.drive_task is not None:
            try:
                await run.drive_task  # let the drain flush the terminal event + close
            except asyncio.CancelledError:
                pass
        return {"run_id": run_id, "cancelled": True}

    return app


app = create_app()
