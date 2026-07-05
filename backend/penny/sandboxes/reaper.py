"""Dispatch + idle-reaper state machine with the cancellable reap lease.

The reaper (a Fly cron sweep) snapshots an idle conversation's ``/workspace``
then terminates the sandbox — a pair that is not atomic, since the snapshot
hands control to Modal for up to 55s. A returning turn can arrive mid-snapshot.
The four-state machine (see :mod:`.store`) plus a ``reap_epoch`` lease makes the
race safe: the reaper only terminates after re-confirming its epoch under the
lock, and a returning turn bumps the epoch to cancel the pending terminate.

Because a committed snapshot is only ever taken from an ``IDLE`` (quiescent)
box, whether ``snapshot_directory`` is point-in-time consistent is irrelevant to
correctness.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from .provider import SandboxHandle, SandboxProvider
from .store import ConversationSandbox, SandboxState

SNAPSHOT_TIMEOUT = 55.0
IDLE_TIMEOUT = 15 * 60.0


class SandboxBusy(Exception):
    """A turn is already active for this conversation (surfaces as 409)."""


async def dispatch_turn(
    rec: ConversationSandbox, provider: SandboxProvider, *, now: float
) -> SandboxHandle:
    """Acquire a live sandbox for the next turn, stealing it back from a reaper
    if one is mid-snapshot. Transitions the record to ``ACTIVE``.
    """
    async with rec.lock:
        if rec.state is SandboxState.ACTIVE:
            raise SandboxBusy(rec.conversation_id)

        if rec.state is SandboxState.REAPING:
            # Steal the box back: bump the epoch so the reaper's pending
            # terminate is cancelled, and reuse the still-alive sandbox.
            rec.reap_epoch += 1
            handle = SandboxHandle(rec.sandbox_id, rec.tunnel_url)  # type: ignore[arg-type]
        elif rec.state is SandboxState.TERMINATED or rec.sandbox_id is None:
            # Cold path: create fresh, or restore the workspace delta if we have one.
            if rec.snapshot_image_id:
                handle = await provider.restore(rec.conversation_id, rec.snapshot_image_id)
            else:
                handle = await provider.create(rec.conversation_id)
            rec.sandbox_id = handle.sandbox_id
            rec.tunnel_url = handle.tunnel_url
        else:  # IDLE — warm reuse
            handle = SandboxHandle(rec.sandbox_id, rec.tunnel_url)  # type: ignore[arg-type]

        rec.state = SandboxState.ACTIVE
        rec.last_activity_at = now
        return handle


async def on_turn_end(rec: ConversationSandbox, *, now: float) -> None:
    """Return the conversation to IDLE and restart its idle clock."""
    async with rec.lock:
        if rec.state is SandboxState.ACTIVE:
            rec.state = SandboxState.IDLE
            rec.last_activity_at = now


async def reap_if_idle(
    rec: ConversationSandbox, provider: SandboxProvider, *, now: float, idle_timeout: float = IDLE_TIMEOUT
) -> bool:
    """One reaper tick. Returns True iff it terminated the sandbox this call."""
    async with rec.lock:
        if rec.state is not SandboxState.IDLE:
            return False
        if now - rec.last_activity_at < idle_timeout:
            return False
        if rec.sandbox_id is None:
            rec.state = SandboxState.TERMINATED
            return False
        rec.state = SandboxState.REAPING
        rec.reap_epoch += 1
        mine = rec.reap_epoch
        sandbox_id = rec.sandbox_id

    # Snapshot OUTSIDE the lock — the box is still alive and quiescent.
    try:
        image_id = await asyncio.wait_for(provider.snapshot(sandbox_id), SNAPSHOT_TIMEOUT)
    except (TimeoutError, Exception) as exc:  # noqa: BLE001 - any snapshot failure
        logger.bind(conversation_id=rec.conversation_id).warning("reap snapshot failed: {}", exc)
        async with rec.lock:
            if rec.state is SandboxState.REAPING and rec.reap_epoch == mine:
                rec.state = SandboxState.IDLE  # keep the box, retry next tick
        return False

    async with rec.lock:
        if rec.state is not SandboxState.REAPING or rec.reap_epoch != mine:
            # A turn stole the box back during the snapshot — do NOT terminate;
            # the (possibly torn) image is discarded.
            return False
        rec.snapshot_image_id = image_id  # commit only when uncontested + quiescent
        rec.state = SandboxState.TERMINATED

    await provider.terminate(sandbox_id)
    return True
