"""Output pipeline for markdown/HTML generation and target fanout."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from transactoid.adapters.storage.r2 import R2StorageError
from transactoid.jobs.report.html_renderer import render_report_html
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    ArtifactRecord,
    OutputTarget,
)
from transactoid.tools.storage.upload_tool import upload_artifact

_DEFAULT_LOCAL_DIR = ".transactoid/artifacts"


class OutputPipeline:
    """Generates output artifacts and fans them out to configured targets."""

    def process(
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
        timestamp = datetime.now(UTC)
        artifacts: list[ArtifactRecord] = []

        html_text: str | None = None
        if request.save_html:
            html_text = render_report_html(report_text)

        for target in request.output_targets:
            if target == OutputTarget.R2:
                artifacts.extend(
                    _upload_to_r2(
                        report_text=report_text,
                        html_text=html_text,
                        request=request,
                        timestamp=timestamp,
                    )
                )
            elif target == OutputTarget.LOCAL:
                artifacts.extend(
                    _write_to_local(
                        report_text=report_text,
                        html_text=html_text,
                        request=request,
                        run_id=run_id,
                    )
                )

        return html_text, tuple(artifacts)


def _upload_to_r2(
    *,
    report_text: str,
    html_text: str | None,
    request: AgentRunRequest,
    timestamp: datetime,
) -> list[ArtifactRecord]:
    """Upload markdown and optional HTML artifacts to R2."""
    records: list[ArtifactRecord] = []

    if request.save_md:
        try:
            md_body = report_text.encode("utf-8")
            result = upload_artifact(
                artifact_type="report-md",
                body=md_body,
                content_type="text/markdown; charset=utf-8",
                timestamp=timestamp,
            )
            records.append(
                ArtifactRecord(
                    artifact_type="report-md",
                    key=result.key,
                    target=OutputTarget.R2,
                    content_type=result.content_type,
                    size_bytes=len(md_body),
                    created_at=timestamp,
                )
            )
            logger.info("Uploaded report-md to R2: {}", result.key)
        except R2StorageError as exc:
            logger.error("R2 upload failed for report-md: {}", exc)

    if request.save_html and html_text is not None:
        try:
            html_body = html_text.encode("utf-8")
            result = upload_artifact(
                artifact_type="report-html",
                body=html_body,
                content_type="text/html; charset=utf-8",
                timestamp=timestamp,
            )
            records.append(
                ArtifactRecord(
                    artifact_type="report-html",
                    key=result.key,
                    target=OutputTarget.R2,
                    content_type=result.content_type,
                    size_bytes=len(html_body),
                    created_at=timestamp,
                )
            )
            logger.info("Uploaded report-html to R2: {}", result.key)
        except R2StorageError as exc:
            logger.error("R2 upload failed for report-html: {}", exc)

    return records


def _write_to_local(
    *,
    report_text: str,
    html_text: str | None,
    request: AgentRunRequest,
    run_id: str,
) -> list[ArtifactRecord]:
    """Write markdown and optional HTML artifacts to a local directory."""
    local_dir = Path(request.local_dir or _DEFAULT_LOCAL_DIR)
    run_dir = local_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    records: list[ArtifactRecord] = []
    timestamp = datetime.now(UTC)

    if request.save_md:
        md_path = run_dir / "report.md"
        md_body = report_text.encode("utf-8")
        md_path.write_bytes(md_body)
        records.append(
            ArtifactRecord(
                artifact_type="report-md",
                key=str(md_path),
                target=OutputTarget.LOCAL,
                content_type="text/markdown; charset=utf-8",
                size_bytes=len(md_body),
                created_at=timestamp,
            )
        )
        logger.info("Wrote report-md to {}", md_path)

    if request.save_html and html_text is not None:
        html_path = run_dir / "report.html"
        html_body = html_text.encode("utf-8")
        html_path.write_bytes(html_body)
        records.append(
            ArtifactRecord(
                artifact_type="report-html",
                key=str(html_path),
                target=OutputTarget.LOCAL,
                content_type="text/html; charset=utf-8",
                size_bytes=len(html_body),
                created_at=timestamp,
            )
        )
        logger.info("Wrote report-html to {}", html_path)

    return records
