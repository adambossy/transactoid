from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

ToolCallKind = Literal["execute", "fetch", "edit", "other"]


@dataclass(frozen=True, slots=True)
class CoreSession:
    """Provider-agnostic session handle."""

    session_id: str
    native_session: object


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Normalized tool call record across runtimes."""

    call_id: str
    tool_name: str
    arguments: dict[str, object]
    output: dict[str, object] | str
    status: Literal["completed", "failed"]


@dataclass(frozen=True, slots=True)
class CoreRunResult:
    """Normalized run result across runtimes."""

    final_text: str
    tool_calls: list[ToolCallRecord]
    raw_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class TextDeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ThoughtDeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStartedEvent:
    call_id: str
    tool_name: str
    kind: ToolCallKind


@dataclass(frozen=True, slots=True)
class ToolCallArgsDeltaEvent:
    call_id: str
    delta: str


@dataclass(frozen=True, slots=True)
class ToolCallCompletedEvent:
    call_id: str


@dataclass(frozen=True, slots=True)
class ToolOutputEvent:
    call_id: str
    output: dict[str, object] | str


@dataclass(frozen=True, slots=True)
class TurnCompletedEvent:
    final_text: str


CoreEvent = (
    TextDeltaEvent
    | ThoughtDeltaEvent
    | ToolCallStartedEvent
    | ToolCallArgsDeltaEvent
    | ToolCallCompletedEvent
    | ToolOutputEvent
    | TurnCompletedEvent
)


def classify_tool_kind(tool_name: str) -> ToolCallKind:
    """Map tool name to a coarse UI kind."""
    kind_map: dict[str, ToolCallKind] = {
        "sync_transactions": "fetch",
        "run_sql": "execute",
        "recategorize_merchant": "edit",
        "tag_transactions": "edit",
        "list_accounts": "fetch",
        "list_plaid_accounts": "fetch",
    }
    return kind_map.get(tool_name, "other")


@runtime_checkable
class CoreRuntime(Protocol):
    """Provider-agnostic runtime interface."""

    def start_session(self, session_key: str) -> CoreSession:
        """Create or load a runtime session for conversation memory."""
        ...

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        """Run a full non-streaming turn."""
        ...

    def run_streamed(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        """Run a streaming turn emitting canonical runtime events."""
        ...

    async def close(self) -> None:
        """Close provider resources if needed."""
        ...
