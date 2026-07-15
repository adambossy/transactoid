"""GET /api/conversations: the drawer's list shape, incl. session_mode."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from penny.api.auth import request_context
import penny.api.main as main
from penny.api.persistence.store import ConversationStore
from penny.tenancy.context import RequestContext, SessionMode


def test_conversation_list_carries_session_mode(isolated_db):
    # input: one individual and one joint conversation for the same principal
    ctx = RequestContext(
        user_id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        session_mode=SessionMode.INDIVIDUAL,
    )
    store = ConversationStore()
    store.create_schema()
    store.ensure_conversation("c-ind", ctx, session_mode="individual")
    store.ensure_conversation("c-joint", ctx, session_mode="joint")

    # act
    main.app.dependency_overrides[request_context] = lambda: ctx
    try:
        with TestClient(main.app) as client:
            r = client.get("/api/conversations")
    finally:
        main.app.dependency_overrides.pop(request_context, None)

    # expected: each entry says whether it is a shared (joint) space, so the
    # client can decide where the participant-avatar stack belongs
    assert r.status_code == 200
    conversations = r.json()["conversations"]
    assert {"id", "title", "updated_at", "session_mode"} <= set(conversations[0])
    modes = {c["id"]: c["session_mode"] for c in conversations}
    assert modes == {"c-ind": "individual", "c-joint": "joint"}
