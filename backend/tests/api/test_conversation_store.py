"""ConversationStore: seq monotonicity, upsert idempotency, titling."""

from __future__ import annotations

from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from penny.api.persistence.models import WebBase
from penny.api.persistence.store import ConversationStore
from penny.tenancy.context import RequestContext, SessionMode

# The single principal these store-mechanics tests run as; access checks pass
# because every call in a test shares this context.
_CTX = RequestContext(user_id=uuid.uuid4(), household_id=uuid.uuid4())


def _make_store(tmp_path: Path) -> ConversationStore:
    """Build a ConversationStore over a fresh tmp SQLite web DB."""
    engine = create_engine(f"sqlite:///{tmp_path / 'web.db'}")
    engine = engine.execution_options(schema_translate_map={"web": None})
    WebBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    return ConversationStore(session_factory=factory)


def _seqs_and_roles(store: ConversationStore, conversation_id: str):
    rows = store.get_conversation_messages(conversation_id, _CTX)
    return [(row.seq, row.role, row.status) for row in rows]


def test_seq_is_monotonic_across_user_and_assistant(tmp_path: Path):
    # input
    conversation_id = "conv-1"

    # setup
    store = _make_store(tmp_path)
    store.ensure_conversation(conversation_id, _CTX)

    # act
    store.append_user_message(conversation_id, _CTX, ai_sdk_message_id="u1", text="hi")
    store.upsert_assistant_message(
        conversation_id,
        _CTX,
        ai_sdk_message_id="run_1",
        parts=[{"type": "text", "text": "hello", "state": "done"}],
        status="complete",
    )
    store.append_user_message(
        conversation_id, _CTX, ai_sdk_message_id="u2", text="again"
    )
    output = _seqs_and_roles(store, conversation_id)

    # expected
    expected_output = [
        (0, "user", "complete"),
        (1, "assistant", "complete"),
        (2, "user", "complete"),
    ]
    assert output == expected_output


def test_user_turn_is_stamped_with_its_sender(tmp_path: Path):
    # input: a joint-session context — exactly where attribution must not
    # collapse to the nil sentinel that effective_user_id would produce.
    conversation_id = "conv-sender"
    ctx = RequestContext(
        user_id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        session_mode=SessionMode.JOINT,
    )

    # setup
    store = _make_store(tmp_path)
    store.ensure_conversation(conversation_id, ctx, session_mode="joint")

    # act
    store.append_user_message(conversation_id, ctx, ai_sdk_message_id="u1", text="hi")
    store.upsert_assistant_message(
        conversation_id,
        ctx,
        ai_sdk_message_id="run_1",
        parts=[{"type": "text", "text": "hello", "state": "done"}],
        status="complete",
    )
    rows = store.get_conversation_messages(conversation_id, ctx)
    output = [(row.role, row.sender_user_id) for row in rows]

    # expected: the user turn carries the real member id; assistant turns none
    expected_output = [("user", ctx.user_id), ("assistant", None)]
    assert output == expected_output


def test_upsert_assistant_is_idempotent_by_ai_sdk_id(tmp_path: Path):
    # input
    conversation_id = "conv-2"

    # setup: a streaming placeholder, then finalize the same run
    store = _make_store(tmp_path)
    store.ensure_conversation(conversation_id, _CTX)
    store.upsert_assistant_message(
        conversation_id, _CTX, ai_sdk_message_id="run_9", parts=[], status="streaming"
    )

    # act: finalize the same ai_sdk_message_id
    store.upsert_assistant_message(
        conversation_id,
        _CTX,
        ai_sdk_message_id="run_9",
        parts=[{"type": "text", "text": "done", "state": "done"}],
        status="complete",
    )
    rows = store.get_conversation_messages(conversation_id, _CTX)
    output = {
        "count": len(rows),
        "seq": rows[0].seq,
        "status": rows[0].status,
        "parts": rows[0].parts,
    }

    # expected: one row, reconciled in place
    expected_output = {
        "count": 1,
        "seq": 0,
        "status": "complete",
        "parts": [{"type": "text", "text": "done", "state": "done"}],
    }
    assert output == expected_output


def test_set_title_if_unset_keeps_first_user_message(tmp_path: Path):
    # input
    conversation_id = "conv-3"

    # setup
    store = _make_store(tmp_path)
    store.ensure_conversation(conversation_id, _CTX)

    # act: derive once, then a second derive must not overwrite
    store.set_title_if_unset(conversation_id, "  How much   did I spend  ")
    store.set_title_if_unset(conversation_id, "a later turn")
    with store.session() as session:
        from penny.api.persistence.models import Conversation

        output = session.get(Conversation, conversation_id).title

    # expected: whitespace-collapsed first message wins
    expected_output = "How much did I spend"
    assert output == expected_output


def test_list_conversations_newest_first_and_tenant_scoped(tmp_path: Path):
    from datetime import datetime

    from penny.api.persistence.models import Conversation

    # setup: two household members. Alice's solo thread + a joint thread are
    # visible to Alice; Bob's solo thread is not.
    store = _make_store(tmp_path)
    household = uuid.uuid4()
    alice = RequestContext(user_id=uuid.uuid4(), household_id=household)
    bob = RequestContext(user_id=uuid.uuid4(), household_id=household)

    store.ensure_conversation("alice-solo", alice)
    store.ensure_conversation("bob-solo", bob)
    store.ensure_conversation("shared", bob, session_mode="joint")

    # Stamp distinct updated_at so newest-first ordering is deterministic.
    with store.session() as session:
        session.get(Conversation, "alice-solo").updated_at = datetime(2026, 1, 1)
        session.get(Conversation, "shared").updated_at = datetime(2026, 2, 1)

    # act
    rows = store.list_conversations(alice)
    output = [row.conversation_id for row in rows]

    # expected: joint thread (newer) leads, then Alice's solo; Bob's solo hidden
    expected_output = ["shared", "alice-solo"]
    assert output == expected_output


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
