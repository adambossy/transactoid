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
    """Claude runtime scaffold with fail-fast startup behavior.

    IMPLEMENTATION NOTES FOR CLAUDE AGENT SDK WIRING:
    ===================================================

    When implementing this runtime, use Claude Agent SDK's native skill support:

    1. Enable skills with SDK settings:
       - setting_sources=["project", "user"]
       - Enables discovery from .claude/skills (project) and ~/.claude/skills (user)

    2. Ensure tool permissions include Skill tool:
       - The Skill tool is required for Claude to load and execute skill instructions
       - Include filesystem tools (Read, Glob, Grep) for reading SKILL.md files

    3. No custom emulation layer needed:
       - Claude handles skill discovery and loading natively
       - Skills are always enabled (no feature flags)
       - No max auto-load limit

    4. Skill precedence (handled by Claude SDK):
       - Project skills (.claude/skills) override user skills (~/.claude/skills)
       - Built-in skills are not part of Claude's native skill system

    5. Configuration:
       - Use config.skills_project_dir and config.skills_user_dir
       - These correspond to Claude's setting_sources locations
       - config.skills_builtin_dir is not applicable to Claude runtime
    """

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
