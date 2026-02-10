"""Tests for the upload artifact tool."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from transactoid.adapters.storage.r2 import (
    R2Config,
    R2StoredObject,
    R2UploadError,
)
from transactoid.tools.storage.upload_tool import UploadArtifactTool, upload_artifact


def _make_config() -> R2Config:
    return R2Config(
        account_id="abc123",
        access_key_id="AKID",
        secret_access_key="secret",
        bucket="transactoid-runs",
    )


class TestUploadArtifact:
    @patch("transactoid.adapters.storage.r2.boto3")
    def test_generates_key_and_uploads(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = _make_config()
        ts = datetime(2026, 2, 10, 3, 38, 0, tzinfo=UTC)

        result = upload_artifact(
            artifact_type="report-md",
            body=b"# Report",
            content_type="text/markdown; charset=utf-8",
            timestamp=ts,
            config=config,
        )

        expected = R2StoredObject(
            key="report-md/20260210T033800Z-report-md",
            bucket="transactoid-runs",
            content_type="text/markdown; charset=utf-8",
        )
        assert result == expected

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_passes_body_to_put_object(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = _make_config()
        ts = datetime(2026, 2, 10, 3, 38, 0, tzinfo=UTC)

        upload_artifact(
            artifact_type="report-html",
            body=b"<html>Report</html>",
            content_type="text/html; charset=utf-8",
            timestamp=ts,
            config=config,
        )

        mock_client.put_object.assert_called_once_with(
            Bucket="transactoid-runs",
            Key="report-html/20260210T033800Z-report-html",
            Body=b"<html>Report</html>",
            ContentType="text/html; charset=utf-8",
        )

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_propagates_upload_error(self, mock_boto3: MagicMock) -> None:
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "forbidden"}},
            "PutObject",
        )
        mock_boto3.client.return_value = mock_client
        config = _make_config()

        with pytest.raises(R2UploadError, match="Failed to upload"):
            upload_artifact(
                artifact_type="report-md",
                body=b"data",
                content_type="text/plain",
                config=config,
            )


class TestUploadArtifactTool:
    @patch("transactoid.adapters.storage.r2.boto3")
    def test_execute_returns_success(self, mock_boto3, monkeypatch):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        monkeypatch.setenv("R2_ACCOUNT_ID", "abc123")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKID")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("R2_BUCKET", "transactoid-runs")

        tool = UploadArtifactTool()

        result = asyncio.run(
            tool.execute(
                artifact_type="report-md",
                body="# Report",
                content_type="text/markdown; charset=utf-8",
            )
        )

        assert result["status"] == "success"
        assert result["key"].startswith("report-md/")
        assert result["bucket"] == "transactoid-runs"
