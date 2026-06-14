"""Delivery tools — upload reports to R2 and email them.

These wrap ``penny.tools._services.uploader.upload_artifact`` and
``penny.services.email.EmailService`` so the agent (or the
``render-report-html`` skill) can hand off a rendered report end-to-end.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
from typing import Any

from agent_harness import tool

from penny.services.email import EmailService, SMTPConfig
from penny.tools._services.uploader import upload_artifact


def _coerce_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_email_service() -> EmailService:
    """Construct the EmailService from env (mirrors the legacy report mailer).

    Defaults to SMTP — the proven Gmail path the legacy product used; set
    ``EMAIL_PROVIDER=resend`` to use Resend instead (which requires a verified
    Resend sender domain). For SMTP the From defaults to ``SMTP_USERNAME``
    (Gmail rewrites From to the authenticated account regardless).
    """
    provider = os.environ.get("EMAIL_PROVIDER", "smtp").strip().lower()
    from_name = os.environ.get("EMAIL_FROM_NAME", "Penny Reports")
    if provider == "smtp":
        from_address = os.environ.get("EMAIL_FROM") or os.environ.get(
            "SMTP_USERNAME", ""
        )
        smtp_config = SMTPConfig(
            host=os.environ.get("SMTP_HOST", ""),
            port=int(os.environ.get("SMTP_PORT") or "587"),
            username=os.environ.get("SMTP_USERNAME", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            use_tls=_coerce_bool(os.environ.get("SMTP_USE_TLS"), default=True),
            use_ssl=_coerce_bool(os.environ.get("SMTP_USE_SSL"), default=False),
        )
        return EmailService(
            provider="smtp",
            from_address=from_address,
            from_name=from_name,
            smtp_config=smtp_config,
        )
    from_address = os.environ.get("EMAIL_FROM", "reports@transactoid.com")
    return EmailService(
        provider="resend", from_address=from_address, from_name=from_name
    )


@tool
async def upload_artifact_to_r2(
    artifact_type: str,
    body: str,
    content_type: str,
) -> dict[str, Any]:
    """Upload an artifact (report HTML / markdown / etc.) to Cloudflare R2.

    R2 credentials are read from env (``R2_ENDPOINT_URL``, ``R2_BUCKET``,
    ``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``).

    Args:
        artifact_type: Logical type, e.g. ``report-html``, ``report-md``.
        body: UTF-8 body to upload.
        content_type: MIME type, e.g. ``text/html; charset=utf-8``.

    Returns:
        ``{"status": "success", "key": ..., "bucket": ..., "content_type": ...}``
        on success; ``{"status": "error", "message": ...}`` on failure.
    """

    def _run() -> dict[str, Any]:
        try:
            stored = upload_artifact(
                artifact_type=artifact_type,
                body=body.encode("utf-8"),
                content_type=content_type,
                timestamp=datetime.now(UTC),
            )
            return {
                "status": "success",
                "key": stored.key,
                "bucket": stored.bucket,
                "content_type": stored.content_type,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)


@tool
async def send_email_report(
    to: list[str],
    subject: str,
    html_content: str,
    text_content: str,
) -> dict[str, Any]:
    """Email a rendered report via the configured Resend (or SMTP) provider.

    Args:
        to: One or more recipient addresses.
        subject: Email subject line.
        html_content: HTML body.
        text_content: Plain-text fallback body.
    """

    def _run() -> dict[str, Any]:
        try:
            service = _build_email_service()
            result = service.send_report(
                to=to,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )
            return {
                "status": "success" if result.success else "error",
                "message_id": result.message_id,
                "error": result.error,
            }
        except Exception as exc:
            return {"status": "error", "message_id": None, "error": str(exc)}

    return await asyncio.to_thread(_run)
