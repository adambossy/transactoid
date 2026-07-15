"""Stored conversation messages convert to AI SDK UIMessage JSON.

conversation_to_ui is near-passthrough: parts were captured in UI shape, so
hydration just wraps each row with its id/role. These tests cover every part
type (text, reasoning, tool output, tool-output-error, stream error).
"""

from __future__ import annotations

from typing import Any
import uuid

from penny.api.hydration import conversation_to_ui


class _Row:
    """Minimal stand-in for a ConversationMessage row (only fields read)."""

    def __init__(
        self,
        *,
        ai_sdk_message_id: str | None,
        seq: int,
        role: str,
        parts: list[dict[str, Any]],
        sender_user_id: uuid.UUID | None = None,
    ) -> None:
        self.ai_sdk_message_id = ai_sdk_message_id
        self.seq = seq
        self.role = role
        self.parts = parts
        self.sender_user_id = sender_user_id


def test_conversation_to_ui_round_trips_all_part_types():
    # input: a user turn + an assistant turn carrying reasoning, tool output,
    # a tool error, and a stream-level error part.
    sender = uuid.uuid4()
    rows = [
        _Row(
            ai_sdk_message_id="u1",
            seq=0,
            role="user",
            parts=[{"type": "text", "text": "how many?"}],
            sender_user_id=sender,
        ),
        _Row(
            ai_sdk_message_id="run_1",
            seq=1,
            role="assistant",
            parts=[
                {"type": "reasoning", "text": "Let me count.", "state": "done"},
                {
                    "type": "tool-run_sql",
                    "toolCallId": "c1",
                    "state": "output-available",
                    "input": {"query": "SELECT 1"},
                    "output": {"count": 6},
                },
                {
                    "type": "tool-generate_chart",
                    "toolCallId": "c2",
                    "state": "output-error",
                    "input": {"chart_type": "bar"},
                    "errorText": "bad data",
                },
                {"type": "text", "text": "You have 6.", "state": "done"},
                {"type": "error", "errorText": "quota exceeded"},
            ],
        ),
    ]

    # act
    output = conversation_to_ui(rows)

    # expected: parts pass through verbatim, wrapped with id + role; user
    # turns additionally carry their sender attribution.
    expected_output = [
        {
            "id": "u1",
            "role": "user",
            "parts": [{"type": "text", "text": "how many?"}],
            "senderUserId": str(sender),
        },
        {
            "id": "run_1",
            "role": "assistant",
            "parts": [
                {"type": "reasoning", "text": "Let me count.", "state": "done"},
                {
                    "type": "tool-run_sql",
                    "toolCallId": "c1",
                    "state": "output-available",
                    "input": {"query": "SELECT 1"},
                    "output": {"count": 6},
                },
                {
                    "type": "tool-generate_chart",
                    "toolCallId": "c2",
                    "state": "output-error",
                    "input": {"chart_type": "bar"},
                    "errorText": "bad data",
                },
                {"type": "text", "text": "You have 6.", "state": "done"},
                {"type": "error", "errorText": "quota exceeded"},
            ],
        },
    ]
    assert output == expected_output


def test_conversation_to_ui_uses_seq_fallback_id_and_skips_empty():
    # input: a row with no ai_sdk_message_id and an empty placeholder row
    rows = [
        _Row(ai_sdk_message_id=None, seq=3, role="assistant", parts=[]),
        _Row(
            ai_sdk_message_id=None,
            seq=4,
            role="assistant",
            parts=[{"type": "text", "text": "ok", "state": "done"}],
        ),
    ]

    # act
    output = conversation_to_ui(rows)

    # expected: empty row skipped; the other gets a hist_<seq> id
    expected_output = [
        {
            "id": "hist_4",
            "role": "assistant",
            "parts": [{"type": "text", "text": "ok", "state": "done"}],
        }
    ]
    assert output == expected_output


def test_conversation_to_ui_legacy_user_rows_have_null_sender():
    # input: a user row written before sender attribution existed
    rows = [
        _Row(
            ai_sdk_message_id="u1",
            seq=0,
            role="user",
            parts=[{"type": "text", "text": "old message"}],
        )
    ]

    # act
    output = conversation_to_ui(rows)

    # expected: the key is present but null, so the client renders it as today
    expected_output = [
        {
            "id": "u1",
            "role": "user",
            "parts": [{"type": "text", "text": "old message"}],
            "senderUserId": None,
        }
    ]
    assert output == expected_output
