"""Output pipeline for markdown/HTML generation and target fanout."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from promptorium import load_prompt

from transactoid.adapters.storage.r2 import R2StorageError
from transactoid.services.agent_run.types import (
    AgentRunRequest,
    ArtifactRecord,
    OutputTarget,
)
from transactoid.tools.storage.upload_tool import upload_artifact

_DEFAULT_LOCAL_DIR = ".transactoid/artifacts"
_HTML_RENDER_PROMPT_KEY = "report-md-to-html"
_HTML_RENDER_MODEL = "gemini-3-pro-preview"

if TYPE_CHECKING:
    from google.genai.client import Client as GeminiClient


def _import_gemini_client_class() -> type[GeminiClient]:
    """Lazily import Gemini client class."""
    try:
        from google.genai.client import Client
    except ImportError as exc:
        raise RuntimeError(
            "google-genai package is required for HTML rendering."
        ) from exc
    return Client


def _validate_html_document(*, html_text: str) -> str:
    """Enforce strict full-document HTML output."""
    normalized = html_text.strip()
    normalized_lower = normalized.lower()
    if not normalized:
        raise RuntimeError("Gemini HTML renderer returned empty output.")
    if not normalized_lower.startswith("<!doctype html>"):
        raise RuntimeError("Gemini HTML renderer must return a full HTML document.")
    if "<html" not in normalized_lower:
        raise RuntimeError("Gemini HTML renderer output missing <html> tag.")
    if "<head" not in normalized_lower:
        raise RuntimeError("Gemini HTML renderer output missing <head> tag.")
    if "<body" not in normalized_lower:
        raise RuntimeError("Gemini HTML renderer output missing <body> tag.")
    return normalized


def _render_html_with_gemini(*, report_text: str) -> str:
    """Render HTML from markdown report text using Gemini."""
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required for HTML rendering.")

    prompt_template = load_prompt(_HTML_RENDER_PROMPT_KEY)
    render_prompt = prompt_template.replace("{{markdown_report}}", report_text)

    gemini_client_class = _import_gemini_client_class()
    gemini_client = gemini_client_class(api_key=api_key)
    response = gemini_client.models.generate_content(
        model=_HTML_RENDER_MODEL,
        contents=render_prompt,
    )
    response_text = getattr(response, "text", None)
    if not isinstance(response_text, str):
        response_text = str(response)
    return _validate_html_document(html_text=response_text)


def _build_html_text(*, request: AgentRunRequest, report_text: str) -> str:
    """Resolve HTML from markdown report text via Gemini."""
    _ = request
    return _render_html_with_gemini(report_text=report_text)


class OutputPipeline:
    """Generates output artifacts and fans them out to configured targets."""

    def process(
        self,
        *,
        report_text: str,
        request: AgentRunRequest,
        run_id: str,
    ) -> tuple[str | None, tuple[ArtifactRecord, ...]]:
        """Generate artifacts and persist to configured targets."""
        timestamp = datetime.now(UTC)
        artifacts: list[ArtifactRecord] = []

        html_text: str | None = None
        if request.save_html:
            html_text = _build_html_text(request=request, report_text=report_text)

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
