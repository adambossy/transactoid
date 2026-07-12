"""Phase 4 gate (Modal-independent): the reaper/dispatch state machine + races.

Drives the state machine against a fake provider whose snapshot can be paused,
so the two documented races are exercised deterministically:

* a turn arriving mid-snapshot **steals the box back** (no terminate, box reused);
* an uncontested idle reap **commits the snapshot and terminates**.

Plus: a running turn is never reaped, a snapshot failure keeps the box, and a
post-terminate turn cold-restores.
"""

from __future__ import annotations

import asyncio

import pytest

from penny.sandboxes.provider import SandboxHandle
from penny.sandboxes.reaper import SandboxBusy, dispatch_turn, reap_if_idle
from penny.sandboxes.store import ConversationSandbox, SandboxState


class FakeProvider:
    def __init__(self) -> None:
        self.created = 0
        self.restored = 0
        self.snapshots = 0
        self.terminated: list[str] = []
        self.gate: asyncio.Event | None = None
        self.fail = False

    async def create(self, conversation_id: str) -> SandboxHandle:
        self.created += 1
        return SandboxHandle(f"sb-new-{self.created}", "http://tunnel/new")

    async def restore(
        self, conversation_id: str, snapshot_image_id: str
    ) -> SandboxHandle:
        self.restored += 1
        return SandboxHandle(f"sb-restore-{self.restored}", "http://tunnel/restore")

    async def snapshot(self, sandbox_id: str) -> str:
        self.snapshots += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("snapshot failed")
        return f"img-{sandbox_id}"

    async def terminate(self, sandbox_id: str) -> None:
        self.terminated.append(sandbox_id)


def _idle_rec() -> ConversationSandbox:
    return ConversationSandbox(
        conversation_id="c1",
        state=SandboxState.IDLE,
        sandbox_id="sb-1",
        tunnel_url="http://tunnel/1",
        last_activity_at=0.0,
    )


@pytest.mark.asyncio
async def test_running_turn_is_never_reaped() -> None:
    rec = _idle_rec()
    rec.state = SandboxState.ACTIVE
    reaped = await reap_if_idle(rec, FakeProvider(), now=10_000.0, idle_timeout=900)
    assert reaped is False and rec.state is SandboxState.ACTIVE


@pytest.mark.asyncio
async def test_not_idle_long_enough_is_not_reaped() -> None:
    rec = _idle_rec()
    rec.last_activity_at = 9_950.0
    reaped = await reap_if_idle(rec, FakeProvider(), now=10_000.0, idle_timeout=900)
    assert reaped is False and rec.state is SandboxState.IDLE


@pytest.mark.asyncio
async def test_uncontested_reap_commits_and_terminates() -> None:
    rec = _idle_rec()
    provider = FakeProvider()
    reaped = await reap_if_idle(rec, provider, now=10_000.0, idle_timeout=900)
    assert reaped is True
    assert rec.state is SandboxState.TERMINATED
    assert rec.snapshot_image_id == "img-sb-1"
    assert provider.terminated == ["sb-1"]


@pytest.mark.asyncio
async def test_turn_steals_box_back_mid_snapshot() -> None:
    rec = _idle_rec()
    provider = FakeProvider()
    provider.gate = asyncio.Event()  # pause the snapshot mid-flight

    reap = asyncio.create_task(
        reap_if_idle(rec, provider, now=10_000.0, idle_timeout=900)
    )
    # Wait until the reaper has entered REAPING and is inside snapshot().
    while provider.snapshots == 0:
        await asyncio.sleep(0.01)
    assert rec.state is SandboxState.REAPING

    # A returning turn arrives mid-snapshot: it steals the box back.
    handle = await dispatch_turn(rec, provider, now=10_001.0)
    assert rec.state is SandboxState.ACTIVE
    assert handle.sandbox_id == "sb-1"  # reused the still-alive box

    provider.gate.set()  # let the snapshot finish
    reaped = await reap
    assert reaped is False  # epoch mismatch → did NOT terminate
    assert provider.terminated == []
    assert provider.created == 0 and provider.restored == 0


@pytest.mark.asyncio
async def test_snapshot_failure_keeps_the_box() -> None:
    rec = _idle_rec()
    provider = FakeProvider()
    provider.fail = True
    reaped = await reap_if_idle(rec, provider, now=10_000.0, idle_timeout=900)
    assert reaped is False
    assert rec.state is SandboxState.IDLE  # kept, will retry next tick
    assert provider.terminated == []


@pytest.mark.asyncio
async def test_terminated_conversation_cold_restores() -> None:
    rec = _idle_rec()
    provider = FakeProvider()
    # Reap it first (uncontested) → TERMINATED with a snapshot.
    await reap_if_idle(rec, provider, now=10_000.0, idle_timeout=900)
    assert rec.state is SandboxState.TERMINATED

    handle = await dispatch_turn(rec, provider, now=20_000.0)
    assert provider.restored == 1
    assert handle.sandbox_id.startswith("sb-restore")
    assert rec.state is SandboxState.ACTIVE


@pytest.mark.asyncio
async def test_second_concurrent_turn_is_busy() -> None:
    rec = _idle_rec()
    provider = FakeProvider()
    await dispatch_turn(rec, provider, now=1.0)  # now ACTIVE
    with pytest.raises(SandboxBusy):
        await dispatch_turn(rec, provider, now=2.0)
