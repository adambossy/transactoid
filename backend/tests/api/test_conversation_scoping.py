import uuid

import pytest

from penny.api.persistence.store import ConversationAccessError, ConversationStore
from penny.tenancy.context import RequestContext, SessionMode

H1, H2 = uuid.uuid4(), uuid.uuid4()
A, B = uuid.uuid4(), uuid.uuid4()  # spouses in H1
STRANGER = uuid.uuid4()  # user in H2


def _ctx(uid, hid, mode=SessionMode.INDIVIDUAL):
    return RequestContext(user_id=uid, household_id=hid, session_mode=mode)


@pytest.fixture
def store(isolated_db):
    s = ConversationStore()
    s.create_schema()
    return s


def test_individual_thread_hidden_from_spouse(store):
    store.ensure_conversation("c1", _ctx(A, H1), session_mode="individual")
    with pytest.raises(ConversationAccessError):
        store.get_conversation("c1", _ctx(B, H1))


def test_joint_thread_visible_to_household_not_outsiders(store):
    store.ensure_conversation("c2", _ctx(A, H1), session_mode="joint")
    assert store.get_conversation("c2", _ctx(B, H1)).session_mode == "joint"
    with pytest.raises(ConversationAccessError):
        store.get_conversation("c2", _ctx(STRANGER, H2))


def test_owner_and_mode_come_from_ctx_and_are_immutable(store):
    store.ensure_conversation("c3", _ctx(A, H1), session_mode="individual")
    # Re-ensuring with a different mode does not mutate it.
    store.ensure_conversation("c3", _ctx(A, H1), session_mode="joint")
    assert store.get_conversation("c3", _ctx(A, H1)).session_mode == "individual"


def test_invalid_mode_rejected(store):
    with pytest.raises(ValueError):
        store.ensure_conversation("c4", _ctx(A, H1), session_mode="admin")
