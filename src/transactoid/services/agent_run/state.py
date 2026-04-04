"""Cross-provider continuation state persistence for agent runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json

from loguru import logger

from transactoid.adapters.storage.r2 import (
    R2DownloadError,
    download_object_from_r2,
    store_object_in_r2,
)
from transactoid.core.runtime.protocol import CoreRunResult
from transactoid.services.agent_run.types import ArtifactRecord, OutputTarget

_STATE_PREFIX = "agent-runs"


class ContinuationStateError(Exception):
    """Base error for continuation state operations."""


class CorruptContinuationStateError(ContinuationStateError):
    """Raised when continuation state JSON cannot be parsed."""


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A single exchange in a conversation."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ContinuationState:
    """Cross-provider continuation state for an agent run."""

    run_id: str
    turns: list[ConversationTurn]


def build_continuation_state(
    *,
    run_id: str,
    prompt: str,
    core_result: CoreRunResult,
) -> ContinuationState:
    """Build a full ContinuationState from the prompt and runtime result.

    Reconstructs the conversation as: user prompt, then for each tool call
    an assistant turn (function_call) and a tool turn (function_response),
    followed by the final assistant text.

    Args:
        run_id: Unique run identifier.
        prompt: The original user prompt.
        core_result: Result from the runtime containing tool_calls and final_text.

    Returns:
        ContinuationState with the full conversation history.
    """
    turns: list[ConversationTurn] = [
        ConversationTurn(role="user", content=prompt),
    ]

    for tc in core_result.tool_calls:
        turns.append(
            ConversationTurn(
                role="assistant",
                content=json.dumps(
                    {
                        "function_call": {
                            "call_id": tc.call_id,
                            "name": tc.tool_name,
                            "arguments": tc.arguments,
                        }
                    },
                    default=str,
                ),
            )
        )
        turns.append(
            ConversationTurn(
                role="tool",
                content=json.dumps(
                    {
                        "function_response": {
                            "call_id": tc.call_id,
                            "name": tc.tool_name,
                            "output": tc.output,
                            "status": tc.status,
                        }
                    },
                    default=str,
                ),
            )
        )

    turns.append(
        ConversationTurn(role="assistant", content=core_result.final_text),
    )

    return ContinuationState(run_id=run_id, turns=turns)


def upload_continuation_state(
    *,
    run_id: str,
    state: ContinuationState,
) -> ArtifactRecord:
    """Persist continuation state to R2 as session-state.json.

    Args:
        run_id: Unique run identifier.
        state: The continuation state to persist.

    Returns:
        ArtifactRecord for the uploaded object.

    Raises:
        R2StorageError: If the upload fails.
    """
    key = f"{_STATE_PREFIX}/{run_id}/session-state.json"
    body = _serialize_state(state)
    timestamp = datetime.now(UTC)

    store_object_in_r2(
        key=key,
        body=body,
        content_type="application/json",
    )
    logger.info("Uploaded continuation state to R2: {}", key)

    return ArtifactRecord(
        artifact_type="session-state",
        key=key,
        target=OutputTarget.R2,
        content_type="application/json",
        size_bytes=len(body),
        created_at=timestamp,
    )


def download_continuation_state(*, run_id: str) -> ContinuationState:
    """Download and deserialize continuation state from R2.

    Args:
        run_id: The run ID whose continuation state to download.

    Returns:
        Deserialized ContinuationState.

    Raises:
        R2DownloadError: If the state cannot be downloaded.
        CorruptContinuationStateError: If the JSON is malformed or missing fields.
    """
    key = f"{_STATE_PREFIX}/{run_id}/session-state.json"

    try:
        body = download_object_from_r2(key=key)
    except R2DownloadError:
        logger.error("Could not download continuation state for run {}", run_id)
        raise

    try:
        data = json.loads(body)
        turns = [
            ConversationTurn(role=str(turn["role"]), content=str(turn["content"]))
            for turn in data["turns"]
        ]
        return ContinuationState(run_id=str(data["run_id"]), turns=turns)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        msg = f"Corrupt continuation state for run {run_id}"
        raise CorruptContinuationStateError(msg) from exc


def _serialize_state(state: ContinuationState) -> bytes:
    """Serialize a ContinuationState to JSON bytes."""
    data = asdict(state)
    return json.dumps(data, indent=2).encode("utf-8")
