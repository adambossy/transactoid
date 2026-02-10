"""Trace persistence and continuation for agent runs.

Handles uploading trace.sqlite3 and manifest.json to R2 after runs,
and downloading them for continuation via --continue <run-id>.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile

from loguru import logger

from transactoid.adapters.storage.r2 import (
    R2DownloadError,
    R2StorageError,
    download_object_from_r2,
    store_object_in_r2,
)
from transactoid.services.agent_run.types import (
    ArtifactRecord,
    OutputTarget,
    RunManifest,
)

_TRACE_PREFIX = "agent-runs"


def upload_trace(
    *,
    run_id: str,
    trace_path: Path,
    manifest: RunManifest,
) -> list[ArtifactRecord]:
    """Upload trace sqlite and manifest to R2.

    Args:
        run_id: Unique run identifier.
        trace_path: Path to the local trace.sqlite3 file.
        manifest: Run manifest to persist as JSON.

    Returns:
        List of artifact records for uploaded files.
    """
    records: list[ArtifactRecord] = []
    timestamp = datetime.now(UTC)

    trace_key = f"{_TRACE_PREFIX}/{run_id}/trace.sqlite3"
    manifest_key = f"{_TRACE_PREFIX}/{run_id}/manifest.json"

    if trace_path.exists():
        trace_body = trace_path.read_bytes()
        try:
            store_object_in_r2(
                key=trace_key,
                body=trace_body,
                content_type="application/x-sqlite3",
            )
            records.append(
                ArtifactRecord(
                    artifact_type="trace",
                    key=trace_key,
                    target=OutputTarget.R2,
                    content_type="application/x-sqlite3",
                    size_bytes=len(trace_body),
                    created_at=timestamp,
                )
            )
            logger.info("Uploaded trace to R2: {}", trace_key)
        except R2StorageError as exc:
            logger.error("Failed to upload trace: {}", exc)

    manifest_body = _serialize_manifest(manifest)
    try:
        store_object_in_r2(
            key=manifest_key,
            body=manifest_body,
            content_type="application/json",
        )
        records.append(
            ArtifactRecord(
                artifact_type="manifest",
                key=manifest_key,
                target=OutputTarget.R2,
                content_type="application/json",
                size_bytes=len(manifest_body),
                created_at=timestamp,
            )
        )
        logger.info("Uploaded manifest to R2: {}", manifest_key)
    except R2StorageError as exc:
        logger.error("Failed to upload manifest: {}", exc)

    return records


def download_trace(*, run_id: str) -> Path:
    """Download a prior run's trace sqlite from R2.

    Args:
        run_id: The run ID whose trace to download.

    Returns:
        Path to a temporary file containing the trace database.

    Raises:
        R2DownloadError: If the trace cannot be downloaded.
    """
    trace_key = f"{_TRACE_PREFIX}/{run_id}/trace.sqlite3"

    try:
        body = download_object_from_r2(key=trace_key)
    except R2DownloadError:
        logger.error("Could not download trace for run {}", run_id)
        raise

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.write(body)
    tmp.close()

    logger.info("Downloaded trace for run {} to {}", run_id, tmp.name)
    return Path(tmp.name)


def download_manifest(*, run_id: str) -> RunManifest | None:
    """Download a prior run's manifest from R2.

    Args:
        run_id: The run ID whose manifest to download.

    Returns:
        RunManifest if found, None otherwise.
    """
    manifest_key = f"{_TRACE_PREFIX}/{run_id}/manifest.json"

    try:
        body = download_object_from_r2(key=manifest_key)
    except R2DownloadError:
        logger.warning("No manifest found for run {}", run_id)
        return None

    data = json.loads(body)
    return RunManifest(
        run_id=str(data["run_id"]),
        parent_run_id=data.get("parent_run_id"),
        prompt_key=data.get("prompt_key"),
        started_at=datetime.fromisoformat(str(data["started_at"])),
        finished_at=datetime.fromisoformat(str(data["finished_at"])),
        success=bool(data["success"]),
        error=data.get("error"),
    )


def _serialize_manifest(manifest: RunManifest) -> bytes:
    """Serialize a RunManifest to JSON bytes."""
    data = asdict(manifest)
    for key in ("started_at", "finished_at"):
        if isinstance(data[key], datetime):
            data[key] = data[key].isoformat()
    # Serialize artifact records
    artifact_list = []
    for artifact in data.get("artifacts", ()):
        if isinstance(artifact.get("created_at"), datetime):
            artifact["created_at"] = artifact["created_at"].isoformat()
        if isinstance(artifact.get("target"), OutputTarget):
            artifact["target"] = artifact["target"].value
        artifact_list.append(artifact)
    data["artifacts"] = artifact_list
    return json.dumps(data, indent=2).encode("utf-8")
