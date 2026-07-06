"""``reap_idle_sandboxes``: the stateless, durable idle-sandbox sweep.

Live boxes come from Modal (faked here); the idle clock is the persisted
transcript (a faked ``latest_activity``). Covers reaping a long-idle completed
turn, sparing an in-flight / recent / never-persisted conversation, and the
re-check that aborts when a turn arrives mid-sweep.
"""

from __future__ import annotations

from datetime import UTC, datetime

from penny.sandboxes.reaper import reap_idle_sandboxes

NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC).timestamp()
IDLE = 15 * 60.0


class _FakeProvider:
    def __init__(self, boxes: list[tuple[str, str]]) -> None:
        self._boxes = boxes
        self.terminated: list[str] = []

    async def list_active(self) -> list[tuple[str, str]]:
        return list(self._boxes)

    async def terminate(self, sandbox_id: str) -> None:
        self.terminated.append(sandbox_id)


def _msg(role: str, age_s: float) -> tuple[str, datetime]:
    # Naive UTC, exactly as the DB stores updated_at (the reaper must treat a
    # naive timestamp as UTC, not local — see the tz fix in _idle_since).
    return (role, datetime.fromtimestamp(NOW - age_s, tz=UTC).replace(tzinfo=None))


async def test_reaps_a_long_idle_completed_turn():
    provider = _FakeProvider([("sb1", "conv1")])
    activity = {"conv1": _msg("assistant", IDLE + 60)}  # finished 16 min ago
    reaped = await reap_idle_sandboxes(
        provider, activity.get, now=NOW, idle_timeout=IDLE
    )
    assert reaped == ["conv1"]
    assert provider.terminated == ["sb1"]


async def test_spares_an_in_flight_turn():
    provider = _FakeProvider([("sb1", "conv1")])
    activity = {"conv1": _msg("user", IDLE + 60)}  # trailing user message
    reaped = await reap_idle_sandboxes(
        provider, activity.get, now=NOW, idle_timeout=IDLE
    )
    assert reaped == []
    assert provider.terminated == []


async def test_spares_a_recently_finished_turn():
    provider = _FakeProvider([("sb1", "conv1")])
    activity = {"conv1": _msg("assistant", 60)}  # finished 1 min ago
    reaped = await reap_idle_sandboxes(
        provider, activity.get, now=NOW, idle_timeout=IDLE
    )
    assert reaped == []


async def test_spares_a_never_persisted_conversation():
    provider = _FakeProvider([("sb1", "conv1")])
    reaped = await reap_idle_sandboxes(
        provider, lambda _cid: None, now=NOW, idle_timeout=IDLE
    )
    assert reaped == []


async def test_recheck_aborts_when_a_turn_arrives_mid_sweep():
    provider = _FakeProvider([("sb1", "conv1")])
    calls = {"n": 0}

    def latest(_cid: str) -> tuple[str, datetime] | None:
        calls["n"] += 1
        # First read: long-idle → reapable. Second read (pre-terminate re-check):
        # a fresh user turn just arrived → abort.
        return _msg("assistant", IDLE + 60) if calls["n"] == 1 else _msg("user", 0)

    reaped = await reap_idle_sandboxes(provider, latest, now=NOW, idle_timeout=IDLE)
    assert reaped == []
    assert provider.terminated == []
