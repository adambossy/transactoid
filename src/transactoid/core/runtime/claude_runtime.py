from __future__ import annotations

from collections.abc import AsyncIterator

from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.protocol import (
    CoreEvent,
    CoreRunResult,
    CoreRuntime,
    CoreSession,
)
from transactoid.tools.registry import ToolRegistry


class ClaudeCoreRuntime(CoreRuntime):
    """Claude runtime scaffold with fail-fast startup behavior."""

    def __init__(
        self, *, instructions: str, registry: ToolRegistry, config: CoreRuntimeConfig
    ) -> None:
        _ = (instructions, registry, config)
        raise RuntimeError(
            "Claude runtime is selected but Claude Agent SDK wiring "
            "is not yet implemented in this repository."
        )

    def start_session(self, session_key: str) -> CoreSession:
        raise NotImplementedError

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        raise NotImplementedError

    def run_streamed(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        raise NotImplementedError

    async def close(self) -> None:
        return None
