"""Output pipeline for markdown/HTML generation and target fanout."""

from __future__ import annotations

from transactoid.services.agent_run.types import AgentRunRequest, ArtifactRecord


class OutputPipeline:
    """Generates output artifacts and fans them out to configured targets.

    Responsibilities (to be implemented in fly-6nt.3):
    - Markdown artifact creation
    - HTML rendering via GPT
    - Target fanout (R2, local filesystem)
    - Artifact record bookkeeping
    """

    async def process(
        self,
        *,
        report_text: str,
        request: AgentRunRequest,
        run_id: str,
    ) -> tuple[str | None, tuple[ArtifactRecord, ...]]:
        """Generate artifacts and persist to configured targets.

        Args:
            report_text: Raw markdown report from the agent.
            request: The original run request (controls format/target flags).
            run_id: Unique identifier for this run.

        Returns:
            Tuple of (html_text or None, artifact records).
        """
        raise NotImplementedError
