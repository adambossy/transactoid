import uuid

from penny.api.main import _turn_context  # small pure helper for testability
from penny.tenancy.context import RequestContext, SessionMode


def test_turn_context_adopts_conversation_mode():
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    turn = _turn_context(ctx, conversation_mode="joint")
    assert turn.session_mode is SessionMode.JOINT
    assert turn.user_id == ctx.user_id and turn.household_id == ctx.household_id


def test_turn_context_defaults_individual():
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    assert (
        _turn_context(ctx, conversation_mode="individual").session_mode
        is SessionMode.INDIVIDUAL
    )
