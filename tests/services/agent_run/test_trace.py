"""Tests for trace persistence and continuation."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from transactoid.adapters.storage.r2 import R2DownloadError, R2StorageError
from transactoid.services.agent_run.trace import (
    _serialize_manifest,
    download_manifest,
    download_trace,
    upload_trace,
)
from transactoid.services.agent_run.types import (
    ArtifactRecord,
    OutputTarget,
    RunManifest,
)


def _make_manifest(*, success: bool = True) -> RunManifest:
    return RunManifest(
        run_id="abc123",
        parent_run_id=None,
        prompt_key="spending-report",
        started_at=datetime(2026, 2, 10, 3, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 2, 10, 3, 5, 0, tzinfo=UTC),
        success=success,
        error=None if success else "boom",
    )


class TestSerializeManifest:
    def test_datetimes_serialized_as_iso(self):
        manifest = _make_manifest()

        body = _serialize_manifest(manifest)
        data = json.loads(body)

        assert data["started_at"] == "2026-02-10T03:00:00+00:00"
        assert data["finished_at"] == "2026-02-10T03:05:00+00:00"

    def test_artifact_records_serialized(self):
        manifest = RunManifest(
            run_id="abc123",
            parent_run_id=None,
            prompt_key=None,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
            success=True,
            error=None,
            artifacts=(
                ArtifactRecord(
                    artifact_type="trace",
                    key="agent-runs/abc123/trace.sqlite3",
                    target=OutputTarget.R2,
                    content_type="application/x-sqlite3",
                    size_bytes=1024,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ),
        )

        body = _serialize_manifest(manifest)
        data = json.loads(body)

        assert len(data["artifacts"]) == 1
        artifact = data["artifacts"][0]
        assert artifact["target"] == "r2"
        assert artifact["created_at"] == "2026-01-01T00:00:00+00:00"

    def test_roundtrip_produces_valid_json(self):
        manifest = _make_manifest()

        body = _serialize_manifest(manifest)
        data = json.loads(body)

        assert data["run_id"] == "abc123"
        assert data["success"] is True


class TestUploadTrace:
    @patch("transactoid.services.agent_run.trace.store_object_in_r2")
    def test_uploads_trace_and_manifest(self, mock_store, tmp_path):
        trace_file = tmp_path / "trace.sqlite3"
        trace_file.write_bytes(b"sqlite data")
        manifest = _make_manifest()

        records = upload_trace(
            run_id="abc123", trace_path=trace_file, manifest=manifest
        )

        assert mock_store.call_count == 2
        assert len(records) == 2

        trace_record = next(r for r in records if r.artifact_type == "trace")
        manifest_record = next(r for r in records if r.artifact_type == "manifest")

        assert trace_record.key == "agent-runs/abc123/trace.sqlite3"
        assert manifest_record.key == "agent-runs/abc123/manifest.json"

    @patch("transactoid.services.agent_run.trace.store_object_in_r2")
    def test_skips_trace_when_file_missing(self, mock_store):
        missing_path = Path("/nonexistent/trace.sqlite3")
        manifest = _make_manifest()

        records = upload_trace(
            run_id="abc123", trace_path=missing_path, manifest=manifest
        )

        # Only manifest upload called
        assert mock_store.call_count == 1
        assert len(records) == 1
        assert records[0].artifact_type == "manifest"

    @patch("transactoid.services.agent_run.trace.store_object_in_r2")
    def test_trace_upload_error_logged_not_raised(self, mock_store, tmp_path):
        trace_file = tmp_path / "trace.sqlite3"
        trace_file.write_bytes(b"data")
        mock_store.side_effect = [
            R2StorageError("upload failed"),
            MagicMock(),  # manifest succeeds
        ]
        manifest = _make_manifest()

        records = upload_trace(
            run_id="abc123", trace_path=trace_file, manifest=manifest
        )

        # Only manifest record returned
        assert len(records) == 1
        assert records[0].artifact_type == "manifest"


class TestDownloadTrace:
    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_downloads_to_temp_file(self, mock_download):
        mock_download.return_value = b"sqlite trace data"

        result = download_trace(run_id="abc123")

        assert result.exists()
        assert result.read_bytes() == b"sqlite trace data"
        mock_download.assert_called_once_with(key="agent-runs/abc123/trace.sqlite3")
        # Cleanup
        result.unlink()

    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_raises_on_download_error(self, mock_download):
        mock_download.side_effect = R2DownloadError("not found")

        with pytest.raises(R2DownloadError):
            download_trace(run_id="missing-run")


class TestDownloadManifest:
    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_downloads_and_deserializes(self, mock_download):
        manifest_data = {
            "run_id": "abc123",
            "parent_run_id": None,
            "prompt_key": "spending-report",
            "started_at": "2026-02-10T03:00:00+00:00",
            "finished_at": "2026-02-10T03:05:00+00:00",
            "success": True,
            "error": None,
        }
        mock_download.return_value = json.dumps(manifest_data).encode()

        result = download_manifest(run_id="abc123")

        assert result is not None
        assert result.run_id == "abc123"
        assert result.prompt_key == "spending-report"
        assert result.success is True

    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_returns_none_on_download_error(self, mock_download):
        mock_download.side_effect = R2DownloadError("not found")

        result = download_manifest(run_id="missing-run")

        assert result is None

    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_returns_none_on_invalid_json(self, mock_download):
        mock_download.return_value = b"not valid json"

        result = download_manifest(run_id="abc123")

        assert result is None

    @patch("transactoid.services.agent_run.trace.download_object_from_r2")
    def test_returns_none_on_missing_fields(self, mock_download):
        mock_download.return_value = json.dumps({"run_id": "abc123"}).encode()

        result = download_manifest(run_id="abc123")

        assert result is None
