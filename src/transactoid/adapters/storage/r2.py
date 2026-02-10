"""Cloudflare R2 object storage adapter (S3-compatible via boto3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class R2StorageError(Exception):
    """Base error for R2 storage operations."""


class R2ConfigError(R2StorageError):
    """Missing or invalid R2 configuration."""


class R2UploadError(R2StorageError):
    """Failed to upload an object to R2."""


class R2DownloadError(R2StorageError):
    """Failed to download an object from R2."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)


@dataclass(frozen=True, slots=True)
class R2Config:
    """Credentials and bucket info for Cloudflare R2."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass(frozen=True, slots=True)
class R2StoredObject:
    """Metadata returned after a successful upload."""

    key: str
    bucket: str
    content_type: str


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_r2_config_from_env() -> R2Config:
    """Load R2 configuration from environment variables.

    Required env vars: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, R2_BUCKET.

    Raises:
        R2ConfigError: If any required variable is missing.
    """
    missing = [var for var in _REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise R2ConfigError(f"Missing required R2 env var(s): {', '.join(missing)}")

    return R2Config(
        account_id=os.environ["R2_ACCOUNT_ID"],
        access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        bucket=os.environ["R2_BUCKET"],
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _build_client(config: R2Config) -> Any:
    """Create a boto3 S3 client configured for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
    )


def store_object_in_r2(
    *,
    key: str,
    body: bytes,
    content_type: str,
    metadata: dict[str, str] | None = None,
    config: R2Config | None = None,
) -> R2StoredObject:
    """Upload an object to Cloudflare R2.

    Args:
        key: Object key (e.g. ``report-md/20260210T033800Z-report-md``).
        body: Raw bytes to upload.
        content_type: MIME type (e.g. ``text/markdown; charset=utf-8``).
        metadata: Optional user metadata dict.
        config: R2 credentials. Loaded from env if *None*.

    Returns:
        R2StoredObject with the stored key, bucket, and content type.

    Raises:
        R2ConfigError: If config cannot be loaded from env.
        R2UploadError: If the upload fails.
    """
    if config is None:
        config = load_r2_config_from_env()

    client = _build_client(config)

    put_kwargs: dict[str, object] = {
        "Bucket": config.bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
    }
    if metadata:
        put_kwargs["Metadata"] = metadata

    try:
        client.put_object(**put_kwargs)
    except (BotoCoreError, ClientError) as exc:
        msg = f"Failed to upload {key!r} to {config.bucket}: {exc}"
        raise R2UploadError(msg) from exc

    logger.bind(key=key, bucket=config.bucket).info("Uploaded object to R2: {}", key)
    return R2StoredObject(key=key, bucket=config.bucket, content_type=content_type)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_object_from_r2(
    *,
    key: str,
    config: R2Config | None = None,
) -> bytes:
    """Download an object from Cloudflare R2.

    Args:
        key: Object key to download.
        config: R2 credentials. Loaded from env if *None*.

    Returns:
        Raw bytes of the object.

    Raises:
        R2ConfigError: If config cannot be loaded from env.
        R2DownloadError: If the download fails.
    """
    if config is None:
        config = load_r2_config_from_env()

    client = _build_client(config)

    try:
        response = client.get_object(Bucket=config.bucket, Key=key)
        body: bytes = response["Body"].read()
        return body
    except (BotoCoreError, ClientError) as exc:
        msg = f"Failed to download {key!r} from {config.bucket}: {exc}"
        raise R2DownloadError(msg) from exc


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def make_artifact_key(*, artifact_type: str, timestamp: datetime | None = None) -> str:
    """Build an R2 object key for the given artifact type.

    Format: ``<type>/<ts>-<type>``

    Args:
        artifact_type: e.g. ``report-md``, ``report-html``.
        timestamp: UTC datetime; defaults to *now*.

    Returns:
        Formatted object key string.
    """
    if timestamp is None:
        timestamp = datetime.now(UTC)
    ts_str = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return f"{artifact_type}/{ts_str}-{artifact_type}"
