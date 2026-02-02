"""Email service for sending reports via Resend."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any

import resend


@dataclass
class EmailResult:
    """Result of an email send operation."""

    success: bool
    message_id: str | None
    error: str | None


class EmailService:
    """Email service using Resend API."""

    def __init__(
        self,
        api_key: str | None = None,
        from_address: str = "reports@transactoid.com",
        from_name: str = "Transactoid Reports",
    ) -> None:
        """Initialize email service.

        Args:
            api_key: Resend API key. If None, reads from RESEND_API_KEY env var.
            from_address: Email address to send from.
            from_name: Display name for sender.
        """
        self._api_key = api_key or os.environ.get("RESEND_API_KEY", "")
        self._from_address = from_address
        self._from_name = from_name

        if not self._api_key:
            raise ValueError(
                "Resend API key required. Set RESEND_API_KEY env var or pass api_key."
            )

        resend.api_key = self._api_key

    def send_report(
        self,
        to: list[str],
        subject: str,
        html_content: str,
        text_content: str,
        max_retries: int = 3,
    ) -> EmailResult:
        """Send a report email.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            html_content: HTML body content
            text_content: Plain text body content
            max_retries: Maximum retry attempts on failure

        Returns:
            EmailResult with success status and message ID
        """
        from_str = f"{self._from_name} <{self._from_address}>"

        for attempt in range(max_retries):
            try:
                params: resend.Emails.SendParams = {
                    "from": from_str,
                    "to": to,
                    "subject": subject,
                    "html": html_content,
                    "text": text_content,
                }

                response = resend.Emails.send(params)

                # Response is a dict with 'id' key on success
                if isinstance(response, dict) and "id" in response:
                    return EmailResult(
                        success=True,
                        message_id=response["id"],
                        error=None,
                    )

                return EmailResult(
                    success=False,
                    message_id=None,
                    error=f"Unexpected response: {response}",
                )

            except Exception as e:
                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    time.sleep(2**attempt)
                    continue

                return EmailResult(
                    success=False,
                    message_id=None,
                    error=f"Failed after {max_retries} attempts: {e}",
                )

        # Should not reach here, but satisfy type checker
        return EmailResult(
            success=False,
            message_id=None,
            error="Unexpected error in retry loop",
        )

    def send_error_notification(
        self,
        to: list[str],
        error: str,
        job_metadata: dict[str, Any],
    ) -> EmailResult:
        """Send an error notification email.

        Args:
            to: List of recipient email addresses
            error: Error message
            job_metadata: Job metadata dict for debugging

        Returns:
            EmailResult with success status
        """
        subject = "Transactoid Report Failed"

        text_content = f"""Transactoid Report Generation Failed

Error: {error}

Job Metadata:
{self._format_metadata(job_metadata)}

Please check the Fly.io logs for more details.
"""

        html_content = f"""
<html>
<body>
<h1>Transactoid Report Generation Failed</h1>

<h2>Error</h2>
<pre>{error}</pre>

<h2>Job Metadata</h2>
<pre>{self._format_metadata(job_metadata)}</pre>

<p>Please check the Fly.io logs for more details.</p>
</body>
</html>
"""

        return self.send_report(
            to=to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            max_retries=2,  # Fewer retries for error notifications
        )

    def _format_metadata(self, metadata: dict[str, Any]) -> str:
        """Format metadata dict as readable text."""
        lines = []
        for key, value in metadata.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
