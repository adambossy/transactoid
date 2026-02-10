"""Tests for the Cloudflare R2 storage adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from transactoid.adapters.storage.r2 import (
    R2Config,
    R2ConfigError,
    R2StoredObject,
    R2UploadError,
    load_r2_config_from_env,
    make_artifact_key,
    store_object_in_r2,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_ENV = {
    "R2_ACCOUNT_ID": "abc123",
    "R2_ACCESS_KEY_ID": "AKID",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "transactoid-runs",
}


def _make_config() -> R2Config:
    return R2Config(
        account_id="abc123",
        access_key_id="AKID",
        secret_access_key="secret",
        bucket="transactoid-runs",
    )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


class TestLoadR2ConfigFromEnv:
    def test_success_with_all_env_vars(self, monkeypatch):
        for key, val in _FULL_ENV.items():
            monkeypatch.setenv(key, val)

        config = load_r2_config_from_env()

        expected = _make_config()
        assert config == expected
        assert config.endpoint_url == "https://abc123.r2.cloudflarestorage.com"

    @pytest.mark.parametrize("missing_var", list(_FULL_ENV.keys()))
    def test_missing_required_var(self, monkeypatch, missing_var):
        for key, val in _FULL_ENV.items():
            if key != missing_var:
                monkeypatch.setenv(key, val)
            else:
                monkeypatch.delenv(key, raising=False)

        with pytest.raises(R2ConfigError, match=missing_var):
            load_r2_config_from_env()


# ---------------------------------------------------------------------------
# Key formatting
# ---------------------------------------------------------------------------


class TestMakeArtifactKey:
    def test_report_md_key_format(self):
        ts = datetime(2026, 2, 10, 3, 38, 0, tzinfo=UTC)

        key = make_artifact_key(artifact_type="report-md", timestamp=ts)

        assert key == "report-md/20260210T033800Z-report-md"

    def test_report_html_key_format(self):
        ts = datetime(2026, 2, 10, 3, 38, 0, tzinfo=UTC)

        key = make_artifact_key(artifact_type="report-html", timestamp=ts)

        assert key == "report-html/20260210T033800Z-report-html"

    def test_no_extension_suffix(self):
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

        key = make_artifact_key(artifact_type="report-md", timestamp=ts)

        assert not key.endswith(".md")
        assert not key.endswith(".html")

    def test_defaults_to_utc_now(self):
        key = make_artifact_key(artifact_type="report-md")

        assert key.startswith("report-md/")
        assert key.endswith("-report-md")


# ---------------------------------------------------------------------------
# Upload (mock boto3)
# ---------------------------------------------------------------------------


class TestStoreObjectInR2:
    @patch("transactoid.adapters.storage.r2.boto3")
    def test_put_object_called_with_correct_args(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = _make_config()

        result = store_object_in_r2(
            key="report-md/20260210T033800Z-report-md",
            body=b"# Report",
            content_type="text/markdown; charset=utf-8",
            config=config,
        )

        mock_boto3.client.assert_called_once_with(
            "s3",
            endpoint_url="https://abc123.r2.cloudflarestorage.com",
            aws_access_key_id="AKID",
            aws_secret_access_key="secret",
            region_name="auto",
        )
        mock_client.put_object.assert_called_once_with(
            Bucket="transactoid-runs",
            Key="report-md/20260210T033800Z-report-md",
            Body=b"# Report",
            ContentType="text/markdown; charset=utf-8",
        )

        expected = R2StoredObject(
            key="report-md/20260210T033800Z-report-md",
            bucket="transactoid-runs",
            content_type="text/markdown; charset=utf-8",
        )
        assert result == expected

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_metadata_passed_when_provided(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = _make_config()

        store_object_in_r2(
            key="report-md/20260210T033800Z-report-md",
            body=b"# Report",
            content_type="text/markdown; charset=utf-8",
            metadata={"source": "report-job"},
            config=config,
        )

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Metadata"] == {"source": "report-job"}

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_upload_error_wraps_client_error(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "forbidden"}},
            "PutObject",
        )
        mock_boto3.client.return_value = mock_client
        config = _make_config()

        with pytest.raises(R2UploadError, match="Failed to upload"):
            store_object_in_r2(
                key="report-md/test-key",
                body=b"data",
                content_type="text/plain",
                config=config,
            )

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_loads_config_from_env_when_none(self, mock_boto3, monkeypatch):
        for key, val in _FULL_ENV.items():
            monkeypatch.setenv(key, val)
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = store_object_in_r2(
            key="report-md/test",
            body=b"data",
            content_type="text/plain",
        )

        assert result.bucket == "transactoid-runs"
        mock_client.put_object.assert_called_once()


# ---------------------------------------------------------------------------
# Report integration helpers
# ---------------------------------------------------------------------------


class TestReportUploadIntegration:
    @patch("transactoid.adapters.storage.r2.boto3")
    def test_two_uploads_with_exact_key_pattern(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        config = _make_config()
        ts = datetime(2026, 2, 10, 3, 38, 0, tzinfo=UTC)

        md_key = make_artifact_key(artifact_type="report-md", timestamp=ts)
        html_key = make_artifact_key(artifact_type="report-html", timestamp=ts)

        store_object_in_r2(
            key=md_key,
            body=b"# Monthly Report",
            content_type="text/markdown; charset=utf-8",
            config=config,
        )
        store_object_in_r2(
            key=html_key,
            body=b"<html>Report</html>",
            content_type="text/html; charset=utf-8",
            config=config,
        )

        assert mock_client.put_object.call_count == 2
        calls = mock_client.put_object.call_args_list
        assert calls[0].kwargs["Key"] == "report-md/20260210T033800Z-report-md"
        assert calls[0].kwargs["ContentType"] == "text/markdown; charset=utf-8"
        assert calls[1].kwargs["Key"] == "report-html/20260210T033800Z-report-html"
        assert calls[1].kwargs["ContentType"] == "text/html; charset=utf-8"

    @patch("transactoid.adapters.storage.r2.boto3")
    def test_upload_failure_propagates(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "boom"}},
            "PutObject",
        )
        mock_boto3.client.return_value = mock_client
        config = _make_config()

        with pytest.raises(R2UploadError):
            store_object_in_r2(
                key="report-md/test",
                body=b"data",
                content_type="text/markdown; charset=utf-8",
                config=config,
            )
