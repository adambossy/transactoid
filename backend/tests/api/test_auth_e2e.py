"""End-to-end auth battery against the real FastAPI app.

Drives ``penny.api.main.app`` through ``TestClient`` in clerk mode with a faked
verifier (no live Clerk), two spouses A/B in household H1 and a stranger S in
H2. Asserts 401 (no/invalid token), 403 (unknown user), and 404 (IDOR — a
conversation the principal cannot see, cross-user and cross-household), plus the
joint-thread read and the mode-immutability guarantee. The model/stream are
stubbed so a valid POST needs no LLM.
"""

import uuid

from fastapi.testclient import TestClient
import pytest

from penny.adapters.db.models import Household, User
import penny.api.auth as api_auth
import penny.api.main as main
from penny.api.persistence.store import ConversationStore
from penny.auth.jwt_verifier import TokenError
from penny.auth.settings import AuthSettings
from penny.db import get_db
from penny.tenancy.context import RequestContext

CLERK = AuthSettings(
    mode="clerk",
    issuer="https://iss",
    jwks_url="https://iss/jwks",
    audience=None,
    frontend_origin="https://app",
)

H1, H2 = uuid.uuid4(), uuid.uuid4()
A, B, S = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

# Bearer token string -> verified claims. "U" is a valid token for a subject
# with no users row (→ 403); "bad" is not a known token (→ 401).
_CLAIMS = {
    "A": {"sub": "sub_a", "email": "a@x.com", "email_verified": True},
    "B": {"sub": "sub_b", "email": "b@x.com", "email_verified": True},
    "S": {"sub": "sub_s", "email": "s@x.com", "email_verified": True},
    "U": {"sub": "sub_unknown", "email": "u@x.com", "email_verified": True},
}


class _MultiVerifier:
    def verify(self, token):
        claims = _CLAIMS.get(token)
        if claims is None:
            raise TokenError("bad token")
        return claims


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _chat_body(chat_id: str, **extra):
    return {
        "id": chat_id,
        "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
        **extra,
    }


@pytest.fixture
def client(monkeypatch, isolated_db):
    monkeypatch.setattr(api_auth, "get_auth_settings", lambda: CLERK)
    monkeypatch.setattr(api_auth, "get_verifier", lambda: _MultiVerifier())

    db = get_db()
    db.create_schema()
    with db.session() as s:
        s.add_all(
            [
                Household(household_id=H1, name="H1"),
                Household(household_id=H2, name="H2"),
            ]
        )
        s.flush()
        s.add_all(
            [
                User(
                    user_id=A,
                    household_id=H1,
                    email="a@x.com",
                    external_auth_id="sub_a",
                ),
                User(
                    user_id=B,
                    household_id=H1,
                    email="b@x.com",
                    external_auth_id="sub_b",
                ),
                User(
                    user_id=S,
                    household_id=H2,
                    email="s@x.com",
                    external_auth_id="sub_s",
                ),
            ]
        )
    ConversationStore().create_schema()

    # Stub the model/agent/stream so a valid POST /api/chat needs no LLM.
    async def _fake_stream(agent, prompt, *, store, conversation_id, ctx):
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(main, "stream_and_persist", _fake_stream)
    monkeypatch.setattr(main, "build_agent", lambda **k: object())
    monkeypatch.setattr(main, "_get_model", lambda: object())
    return TestClient(main.app)


def _seed_conversation(chat_id: str, owner, household, mode: str) -> ConversationStore:
    store = ConversationStore()
    ctx = RequestContext(user_id=owner, household_id=household)
    store.ensure_conversation(chat_id, ctx, session_mode=mode)
    store.append_user_message(chat_id, ctx, ai_sdk_message_id="m0", text="hi")
    return store


def test_health_stays_public_200(client):
    assert client.get("/api/health").status_code == 200


def test_chat_without_token_401(client):
    assert client.post("/api/chat", json=_chat_body("c")).status_code == 401


def test_chat_with_invalid_token_401(client):
    r = client.post("/api/chat", headers=_bearer("bad"), json=_chat_body("c"))
    assert r.status_code == 401


def test_chat_unknown_user_403(client):
    r = client.post("/api/chat", headers=_bearer("U"), json=_chat_body("c"))
    assert r.status_code == 403


def test_sessions_endpoint_requires_auth_401(client):
    assert client.get("/api/sessions/anything").status_code == 401


def test_sessions_cross_user_conversation_404(client):
    _seed_conversation("c-a-indiv", A, H1, "individual")
    r = client.get("/api/sessions/c-a-indiv", headers=_bearer("B"))
    assert r.status_code == 404


def test_sessions_cross_household_conversation_404(client):
    _seed_conversation("c-a-2", A, H1, "individual")
    r = client.get("/api/sessions/c-a-2", headers=_bearer("S"))
    assert r.status_code == 404


def test_joint_conversation_readable_by_spouse_200(client):
    _seed_conversation("c-joint", A, H1, "joint")
    r = client.get("/api/sessions/c-joint", headers=_bearer("B"))
    assert r.status_code == 200


def test_session_mode_from_body_ignored_on_existing_conversation(client):
    store = _seed_conversation("c-imm", A, H1, "individual")
    # A re-opens the thread asking for joint mode; the stored mode is immutable.
    r = client.post(
        "/api/chat", headers=_bearer("A"), json=_chat_body("c-imm", sessionMode="joint")
    )
    assert r.status_code == 200
    ctx_a = RequestContext(user_id=A, household_id=H1)
    assert store.get_conversation("c-imm", ctx_a).session_mode == "individual"
