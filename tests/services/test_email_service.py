"""Tests for email service provider behavior."""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

from transactoid.services.email_service import EmailService, SMTPConfig


class _FakeSMTP:
    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.did_starttls = False
        self.logged_in_as: tuple[str, str] | None = None
        self.sent_messages_count = 0

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def ehlo(self) -> None:
        return None

    def starttls(self) -> None:
        self.did_starttls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in_as = (username, password)

    def send_message(self, message) -> None:  # type: ignore[no-untyped-def]
        self.sent_messages_count += 1


def test_email_service_requires_resend_api_key_for_resend_provider(
    monkeypatch: Any,
) -> None:
    # input
    input_provider = "resend"

    # helper setup
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    # act
    with pytest.raises(ValueError) as exc_info:
        EmailService(provider=input_provider)

    # expected
    expected_output = "Resend API key required"

    # assert
    assert expected_output in str(exc_info.value)


def test_email_service_smtp_send_report_success(
    monkeypatch: Any,
) -> None:
    # input
    input_to = ["adambossy@gmail.com"]

    # helper setup
    fake_smtp = _FakeSMTP(host="smtp.gmail.com", port=587, timeout=30)

    def create_fake_smtp(host: str, port: int, timeout: int) -> _FakeSMTP:
        return fake_smtp

    monkeypatch.setattr(smtplib, "SMTP", create_fake_smtp)

    service = EmailService(
        provider="smtp",
        from_address="adambossy@gmail.com",
        from_name="Transactoid Reports",
        smtp_config=SMTPConfig(
            host="smtp.gmail.com",
            port=587,
            username="adambossy@gmail.com",
            password="app-password",
            use_tls=True,
            use_ssl=False,
        ),
    )

    # act
    output = service.send_report(
        to=input_to,
        subject="Test",
        html_content="<h1>Hello</h1>",
        text_content="Hello",
        max_retries=1,
    )

    # expected
    expected_output = {
        "success": True,
        "message_id": None,
        "error": None,
        "did_starttls": True,
        "logged_in_as": ("adambossy@gmail.com", "app-password"),
        "sent_messages_count": 1,
    }
    actual_output = {
        "success": output.success,
        "message_id": output.message_id,
        "error": output.error,
        "did_starttls": fake_smtp.did_starttls,
        "logged_in_as": fake_smtp.logged_in_as,
        "sent_messages_count": fake_smtp.sent_messages_count,
    }

    # assert
    assert actual_output == expected_output
