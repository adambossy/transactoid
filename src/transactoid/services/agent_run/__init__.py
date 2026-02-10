"""Agent run service: core orchestration for headless agent execution."""

from __future__ import annotations

from transactoid.services.agent_run.pipeline import OutputPipeline
from transactoid.services.agent_run.service import AgentRunService
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    AgentRunResult,
    ArtifactRecord,
    OutputTarget,
    RunManifest,
)

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRunService",
    "ArtifactRecord",
    "OutputPipeline",
    "OutputTarget",
    "RunManifest",
]
