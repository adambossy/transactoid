import uuid

import pytest

from penny.tenancy.context import (
    NIL_USER_UUID,
    RequestContext,
    SessionMode,
    effective_user_id,
    get_request_context,
    require_request_context,
    reset_request_context,
    set_request_context,
)

U = uuid.UUID("11111111-1111-1111-1111-111111111111")
H = uuid.UUID("22222222-2222-2222-2222-222222222222")


def test_effective_user_is_real_in_individual_mode():
    ctx = RequestContext(user_id=U, household_id=H, session_mode=SessionMode.INDIVIDUAL)
    assert effective_user_id(ctx) == U


def test_effective_user_is_nil_in_joint_mode():
    ctx = RequestContext(user_id=U, household_id=H, session_mode=SessionMode.JOINT)
    assert effective_user_id(ctx) == NIL_USER_UUID


def test_contextvar_roundtrip_and_reset():
    assert get_request_context() is None
    ctx = RequestContext(user_id=U, household_id=H)
    token = set_request_context(ctx)
    assert require_request_context() is ctx
    reset_request_context(token)
    assert get_request_context() is None


def test_require_raises_when_unset():
    with pytest.raises(LookupError):
        require_request_context()
