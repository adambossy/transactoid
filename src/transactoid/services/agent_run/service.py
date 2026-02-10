"""Core agent run orchestration service."""

from __future__ import annotations

from transactoid.services.agent_run.types import AgentRunRequest, AgentRunResult


class AgentRunService:
    """Executes headless agent runs and manages artifact output.

    Responsibilities (to be implemented in fly-6nt.2):
    - Prompt resolution and template variable injection
    - Agent execution via Runner
    - Trace persistence and continuation
    - Delegates to ``OutputPipeline`` for artifact generation and fanout
    - Run manifest creation
    """

    async def execute(self, request: AgentRunRequest) -> AgentRunResult:
        """Execute a single agent run from the given request.

        Args:
            request: Fully-specified run request DTO.

        Returns:
            AgentRunResult with report text, artifacts, and manifest.
        """
        raise NotImplementedError
