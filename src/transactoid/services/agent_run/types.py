"""Request, result, and artifact types for agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import enum


class OutputTarget(enum.Enum):
    """Where to persist run artifacts."""

    R2 = "r2"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Immutable specification for a single agent run.

    Callers build this DTO and hand it to ``AgentRunService.execute``.
    """

    # Prompt source (exactly one should be set)
    prompt: str | None = None
    prompt_key: str | None = None

    # Template variables injected into the resolved prompt
    template_vars: dict[str, str] = field(default_factory=dict)

    # Continuation
    continue_run_id: str | None = None

    # Output formats
    save_md: bool = True
    save_html: bool = True

    # Where to write artifacts
    output_targets: tuple[OutputTarget, ...] = (OutputTarget.R2,)
    local_dir: str | None = None

    # Email
    email_recipients: tuple[str, ...] = ()

    # Agent execution
    max_turns: int = 50

    def __post_init__(self) -> None:
        if self.prompt is None and self.prompt_key is None:
            msg = "Either prompt or prompt_key must be provided"
            raise ValueError(msg)
        if self.prompt is not None and self.prompt_key is not None:
            msg = "Only one of prompt or prompt_key may be provided"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Metadata for a single persisted artifact."""

    artifact_type: str
    key: str
    target: OutputTarget
    content_type: str
    size_bytes: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Summary manifest for a completed agent run."""

    run_id: str
    parent_run_id: str | None
    prompt_key: str | None
    started_at: datetime
    finished_at: datetime
    success: bool
    error: str | None
    artifacts: tuple[ArtifactRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Outcome of a single agent run.

    Returned by ``AgentRunService.execute``.
    """

    run_id: str
    success: bool
    report_text: str
    html_text: str | None
    error: str | None
    duration_seconds: float
    manifest: RunManifest
    artifacts: tuple[ArtifactRecord, ...] = ()
