"""Tests for cross-provider continuation state persistence."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from transactoid.adapters.storage.r2 import R2DownloadError
from transactoid.core.runtime.protocol import CoreRunResult, ToolCallRecord
from transactoid.services.agent_run.state import (
    ContinuationState,
    ConversationTurn,
    CorruptContinuationStateError,
    _serialize_state,
    build_continuation_state,
    download_continuation_state,
    upload_continuation_state,
)
from transactoid.services.agent_run.types import ArtifactRecord, OutputTarget


def _make_state(run_id: str = "run-abc") -> ContinuationState:
    return ContinuationState(
        run_id=run_id,
        turns=[
            ConversationTurn(role="user", content="What did I spend last month?"),
            ConversationTurn(role="assistant", content="You spent $1,200 last month."),
        ],
    )


class TestContinuationStateSerialization:
    def test_continuation_state_serialization_roundtrip(self):
        # input
        state = _make_state()

        # act
        body = _serialize_state(state)
        data = json.loads(body)
        reconstructed = ContinuationState(
            run_id=data["run_id"],
            turns=[
                ConversationTurn(role=t["role"], content=t["content"])
                for t in data["turns"]
            ],
        )

        # assert
        assert reconstructed == state

    def test_serialized_json_contains_expected_fields(self):
        state = _make_state()

        body = _serialize_state(state)
        data = json.loads(body)

        assert data["run_id"] == "run-abc"
        assert len(data["turns"]) == 2
        assert data["turns"][0]["role"] == "user"
        assert data["turns"][1]["role"] == "assistant"


class TestUploadContinuationState:
    @patch("transactoid.services.agent_run.state.store_object_in_r2")
    def test_upload_continuation_state_uses_correct_r2_key(self, mock_store):
        state = _make_state(run_id="run-xyz")

        upload_continuation_state(run_id="run-xyz", state=state)

        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args.kwargs
        assert call_kwargs["key"] == "agent-runs/run-xyz/session-state.json"
        assert call_kwargs["content_type"] == "application/json"

    @patch("transactoid.services.agent_run.state.store_object_in_r2")
    def test_upload_returns_artifact_record_with_correct_fields(self, mock_store):
        state = _make_state(run_id="run-xyz")

        result = upload_continuation_state(run_id="run-xyz", state=state)

        assert isinstance(result, ArtifactRecord)
        assert result.artifact_type == "session-state"
        assert result.key == "agent-runs/run-xyz/session-state.json"
        assert result.target == OutputTarget.R2
        assert result.content_type == "application/json"
        assert result.size_bytes > 0


class TestDownloadContinuationState:
    @patch("transactoid.services.agent_run.state.download_object_from_r2")
    def test_download_continuation_state_deserializes_correctly(self, mock_download):
        # input
        state_data = {
            "run_id": "run-abc",
            "turns": [
                {"role": "user", "content": "How much did I spend?"},
                {"role": "assistant", "content": "You spent $500."},
            ],
        }
        mock_download.return_value = json.dumps(state_data).encode()

        # act
        result = download_continuation_state(run_id="run-abc")

        # expected
        expected = ContinuationState(
            run_id="run-abc",
            turns=[
                ConversationTurn(role="user", content="How much did I spend?"),
                ConversationTurn(role="assistant", content="You spent $500."),
            ],
        )

        # assert
        assert result == expected

    @patch("transactoid.services.agent_run.state.download_object_from_r2")
    def test_download_continuation_state_uses_correct_r2_key(self, mock_download):
        state_data = {
            "run_id": "run-abc",
            "turns": [],
        }
        mock_download.return_value = json.dumps(state_data).encode()

        download_continuation_state(run_id="run-abc")

        mock_download.assert_called_once_with(
            key="agent-runs/run-abc/session-state.json"
        )

    @patch("transactoid.services.agent_run.state.download_object_from_r2")
    def test_download_continuation_state_raises_on_malformed_json(self, mock_download):
        mock_download.return_value = b"not valid json {{{"

        with pytest.raises(
            CorruptContinuationStateError,
            match="Corrupt continuation state for run bad-run",
        ):
            download_continuation_state(run_id="bad-run")

    @patch("transactoid.services.agent_run.state.download_object_from_r2")
    def test_download_continuation_state_raises_on_missing_fields(self, mock_download):
        mock_download.return_value = json.dumps({"run_id": "run-abc"}).encode()

        with pytest.raises(CorruptContinuationStateError):
            download_continuation_state(run_id="run-abc")

    @patch("transactoid.services.agent_run.state.download_object_from_r2")
    def test_download_continuation_state_propagates_r2_error(self, mock_download):
        mock_download.side_effect = R2DownloadError("not found")

        with pytest.raises(R2DownloadError):
            download_continuation_state(run_id="missing-run")


class TestBuildContinuationState:
    def test_no_tool_calls_produces_user_and_assistant_turns(self):
        core_result = CoreRunResult(
            final_text="Simple answer",
            tool_calls=[],
            raw_metadata={},
        )

        state = build_continuation_state(
            run_id="run-1", prompt="Hello", core_result=core_result
        )

        assert len(state.turns) == 2
        assert state.turns[0] == ConversationTurn(role="user", content="Hello")
        assert state.turns[1] == ConversationTurn(
            role="assistant", content="Simple answer"
        )

    def test_tool_calls_produce_intermediate_turns(self):
        core_result = CoreRunResult(
            final_text="Final answer",
            tool_calls=[
                ToolCallRecord(
                    call_id="call_1",
                    tool_name="run_sql",
                    arguments={"sql": "SELECT 1"},
                    output={"rows": [{"1": 1}]},
                    status="completed",
                ),
            ],
            raw_metadata={},
        )

        state = build_continuation_state(
            run_id="run-2", prompt="Query data", core_result=core_result
        )

        assert len(state.turns) == 4
        assert state.turns[0].role == "user"
        assert state.turns[1].role == "assistant"
        assert state.turns[2].role == "tool"
        assert state.turns[3].role == "assistant"

        # Verify function_call turn content
        fc_data = json.loads(state.turns[1].content)
        assert fc_data["function_call"]["name"] == "run_sql"
        assert fc_data["function_call"]["call_id"] == "call_1"

        # Verify function_response turn content
        fr_data = json.loads(state.turns[2].content)
        assert fr_data["function_response"]["name"] == "run_sql"
        assert fr_data["function_response"]["status"] == "completed"

    def test_multiple_tool_calls_interleaved(self):
        core_result = CoreRunResult(
            final_text="Done",
            tool_calls=[
                ToolCallRecord(
                    call_id="c1",
                    tool_name="run_sql",
                    arguments={"sql": "SELECT 1"},
                    output="ok",
                    status="completed",
                ),
                ToolCallRecord(
                    call_id="c2",
                    tool_name="send_email",
                    arguments={"to": "a@b.com"},
                    output="sent",
                    status="completed",
                ),
            ],
            raw_metadata={},
        )

        state = build_continuation_state(
            run_id="run-3", prompt="Do stuff", core_result=core_result
        )

        # user + (fc+fr) * 2 + final assistant = 6
        assert len(state.turns) == 6
        assert state.turns[0].role == "user"
        assert state.turns[1].role == "assistant"
        assert state.turns[2].role == "tool"
        assert state.turns[3].role == "assistant"
        assert state.turns[4].role == "tool"
        assert state.turns[5].role == "assistant"

    def test_run_id_set_on_state(self):
        core_result = CoreRunResult(
            final_text="answer",
            tool_calls=[],
            raw_metadata={},
        )

        state = build_continuation_state(
            run_id="my-run-id", prompt="q", core_result=core_result
        )

        assert state.run_id == "my-run-id"
