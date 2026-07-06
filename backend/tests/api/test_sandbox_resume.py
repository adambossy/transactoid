"""Resume gating + the runner→Fly finalize callback (persistence push).

Display (resume) and persistence (finalize) are decoupled: ``resume_stream``
decides *who may reconnect* to an in-flight turn; ``finalize_turn`` authenticates
the runner's callback and persists the delivered event log. The sandbox/runner
integration is verified end-to-end elsewhere; here we cover the pure gating and
the persist-from-log path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import uuid

from agent_harness.core.events import MessageDelta, MessageEnd, RunEnd, RunStart
from agent_harness.core.models import Message, TextBlock, Usage
from protocol.events import encode_envelope
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from penny.api import sandbox_wiring as sw
from penny.api.mcp_server import Principal
from penny.api.persistence.models import WebBase
from penny.api.persistence.store import ConversationStore
from penny.tenancy.context import RequestContext

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _ctx() -> RequestContext:
    return RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())


def _make_store(tmp_path: Path) -> ConversationStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'web.db'}")
    engine = engine.execution_options(schema_translate_map={"web": None})
    WebBase.metadata.create_all(engine)
    return ConversationStore(session_factory=sessionmaker(bind=engine, class_=Session))


@pytest.fixture(autouse=True)
def _clear_state():
    sw._active.clear()
    sw.mcp_registry._by_token.clear()
    yield
    sw._active.clear()
    sw.mcp_registry._by_token.clear()


# ----- resume gating -------------------------------------------------------


def test_resume_is_none_when_no_active_run():
    assert sw.resume_stream("conv-x", _ctx()) is None


def test_resume_is_none_for_a_different_household():
    owner = _ctx()
    sw._active["conv-x"] = ("http://sandbox", "run_1", str(owner.household_id))
    assert sw.resume_stream("conv-x", _ctx()) is None  # different household


def test_resume_returns_a_stream_for_the_owning_household():
    ctx = _ctx()
    sw._active["conv-x"] = ("http://sandbox", "run_1", str(ctx.household_id))
    assert sw.resume_stream("conv-x", ctx) is not None


# ----- finalize (persistence push) -----------------------------------------


async def test_finalize_rejects_an_unknown_token(tmp_path: Path):
    store = _make_store(tmp_path)
    assert await sw.finalize_turn(store, "conv-x", "bogus-token", []) is False


async def test_finalize_rejects_a_conversation_mismatch(tmp_path: Path):
    store = _make_store(tmp_path)
    ctx = _ctx()
    token = sw.mcp_registry.mint(Principal(conversation_id="conv-A", ctx=ctx))
    # Token is for conv-A; a callback claiming conv-B must be rejected.
    assert await sw.finalize_turn(store, "conv-B", token, []) is False


async def test_finalize_persists_the_delivered_event_log(tmp_path: Path):
    store = _make_store(tmp_path)
    ctx = _ctx()
    conv = "conv-fin"
    store.ensure_conversation(conv, ctx)
    token = sw.mcp_registry.mint(Principal(conversation_id=conv, ctx=ctx))

    final = Message(role="assistant", content=[TextBlock(text="Done.")], timestamp=_TS)
    events = [
        encode_envelope(0, RunStart(run_id="run_1", agent_name="penny", prompt="q")),
        encode_envelope(
            1, MessageDelta(message_id="m", delta="Done.", partial="Done.")
        ),
        encode_envelope(2, MessageEnd(message_id="m", final=final, usage=Usage())),
        encode_envelope(
            3, RunEnd(run_id="run_1", result=None, usage=Usage(), duration_ms=1)
        ),
    ]

    ok = await sw.finalize_turn(store, conv, token, events)
    assert ok is True

    rows = store.get_conversation_messages(conv, ctx)
    assistant = [r for r in rows if r.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].status == "complete"
    assert assistant[0].parts == [{"type": "text", "text": "Done.", "state": "done"}]
    # The one-time capability token is revoked after finalize.
    assert sw.mcp_registry.resolve(token) is None
