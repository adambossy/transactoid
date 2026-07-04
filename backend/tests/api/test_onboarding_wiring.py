"""The chat handler enqueues the consolidated onboarding reminder per turn.

Individual conversations enqueue; joint conversations skip entirely (personal
setup doesn't belong in a shared thread, spec decision).
"""

from __future__ import annotations

from penny.api.main import _maybe_enqueue_onboarding
from penny.reminders import DbReminderQueue
from penny.tenancy.context import RequestContext, SessionMode
from tests.test_onboarding import _ctx  # reuse seeding


async def test_individual_conversation_enqueues(isolated_db):
    ctx = _ctx()
    await _maybe_enqueue_onboarding(ctx, conversation_id="conv-1")
    drained = await DbReminderQueue(ctx).drain("conv-1")
    assert len(drained) == 1 and drained[0].kind == "onboarding"
    assert "connect_plaid" in drained[0].content  # unlinked -> connect nudge


async def test_joint_conversation_skips(isolated_db):
    base = _ctx()
    joint = RequestContext(
        user_id=base.user_id,
        household_id=base.household_id,
        session_mode=SessionMode.JOINT,
    )
    await _maybe_enqueue_onboarding(joint, conversation_id="conv-2")
    assert await DbReminderQueue(base).drain("conv-2") == []
