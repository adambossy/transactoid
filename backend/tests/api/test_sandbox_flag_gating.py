"""The sandbox-only chat endpoints must no-op when PENNY_SANDBOX_TURNS is off.

Regression for PYTHON-B (Sentry): resume/cancel/finalize imported
``sandbox_wiring`` at request time while its ``protocol`` dependency wasn't a
declared backend dependency, so every fresh venv and the prod image 500'd with
ModuleNotFoundError the moment the AI SDK called ``resumeStream()``. The root
fix is packaging — ``protocol`` now ships in the penny-lib workspace member,
so the import always resolves — and off-flag the routes answer with their
natural no-ops: nothing to resume (204), nothing to cancel (false), no valid
capability token (401).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
import pytest

from penny.api.auth import request_context
import penny.api.main as main
from penny.tenancy.context import RequestContext


@pytest.fixture
def client(isolated_db, monkeypatch: pytest.MonkeyPatch) -> TestClient:  # noqa: ARG001
    monkeypatch.delenv("PENNY_SANDBOX_TURNS", raising=False)
    ctx = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())
    main.app.dependency_overrides[request_context] = lambda: ctx
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        main.app.dependency_overrides.pop(request_context, None)


def test_resume_returns_204_when_sandbox_turns_off(client: TestClient):
    r = client.get("/api/chat/conv-1/stream")
    assert r.status_code == 204


def test_cancel_is_a_no_op_when_sandbox_turns_off(client: TestClient):
    r = client.post("/api/chat/conv-1/cancel")
    assert r.status_code == 200
    assert r.json() == {"cancelled": False}


def test_finalize_is_unauthorized_when_sandbox_turns_off(client: TestClient):
    r = client.post(
        "/api/chat/conv-1/finalize",
        json={"events": []},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401
