"""Tool for uploading artifacts to Cloudflare R2."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from transactoid.adapters.storage.r2 import (
    R2Config,
    R2StoredObject,
    make_artifact_key,
    store_object_in_r2,
)
from transactoid.tools.base import StandardTool
from transactoid.tools.protocol import ToolInputSchema


def upload_artifact(
    *,
    artifact_type: str,
    body: bytes,
    content_type: str,
    timestamp: datetime | None = None,
    config: R2Config | None = None,
) -> R2StoredObject:
    """Generate an artifact key and upload the object to R2.

    Combines key generation and upload into a single call.

    Args:
        artifact_type: e.g. ``report-md``, ``report-html``.
        body: Raw bytes to upload.
        content_type: MIME type (e.g. ``text/markdown; charset=utf-8``).
        timestamp: UTC datetime for the key; defaults to *now*.
        config: R2 credentials. Loaded from env if *None*.

    Returns:
        R2StoredObject with the stored key, bucket, and content type.

    Raises:
        R2ConfigError: If config cannot be loaded from env.
        R2UploadError: If the upload fails.
    """
    key = make_artifact_key(artifact_type=artifact_type, timestamp=timestamp)
    return store_object_in_r2(
        key=key,
        body=body,
        content_type=content_type,
        config=config,
    )


class UploadArtifactTool(StandardTool):
    """Tool wrapper exposing artifact upload through the Tool protocol."""

    _name = "upload_artifact"
    _description = (
        "Upload an artifact to Cloudflare R2 storage. "
        "Generates a timestamped key and stores the content."
    )
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "artifact_type": {
                "type": "string",
                "description": (
                    "Artifact type used to build the storage key "
                    "(e.g. 'report-md', 'report-html')"
                ),
            },
            "body": {
                "type": "string",
                "description": "Text content to upload (will be UTF-8 encoded)",
            },
            "content_type": {
                "type": "string",
                "description": "MIME type (e.g. 'text/markdown; charset=utf-8')",
            },
        },
        "required": ["artifact_type", "body", "content_type"],
    }

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        artifact_type: str = kwargs["artifact_type"]
        body_text: str = kwargs["body"]
        content_type: str = kwargs["content_type"]

        result = upload_artifact(
            artifact_type=artifact_type,
            body=body_text.encode("utf-8"),
            content_type=content_type,
        )
        return {
            "status": "success",
            "key": result.key,
            "bucket": result.bucket,
            "content_type": result.content_type,
        }
