"""Tests for the Amazon auth-expired email alert helpers in ``ui.cli``.

Covers ``_is_amazon_auth_expired``, ``_build_amazon_auth_alert``, and
``_inject_alert_html``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import AmazonLoginProfileDB
from transactoid.ui.cli import (
    _AMAZON_AUTH_STALE_DAYS,
    _build_amazon_auth_alert,
    _inject_alert_html,
    _is_amazon_auth_expired,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_test_db(tmp_path: Path) -> DB:
    """Create an isolated SQLite test database."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


def make_profile(
    *,
    profile_key: str = "primary",
    display_name: str = "Primary Account",
    enabled: bool = True,
    last_auth_at: datetime | None = None,
    last_auth_status: str | None = None,
) -> AmazonLoginProfileDB:
    """Build a detached ``AmazonLoginProfileDB`` for unit-level checks."""
    return AmazonLoginProfileDB(
        profile_key=profile_key,
        display_name=display_name,
        enabled=enabled,
        last_auth_at=last_auth_at,
        last_auth_status=last_auth_status,
    )


def set_profile_auth_state(
    db: DB,
    *,
    profile_key: str,
    last_auth_at: datetime | None,
    last_auth_status: str | None,
) -> None:
    """Force a profile's auth fields to specific values (bypassing the
    facade's ``utcnow()`` setter so tests can place auth in the past)."""
    with db.session() as session:
        profile = (
            session.query(AmazonLoginProfileDB)
            .filter(AmazonLoginProfileDB.profile_key == profile_key)
            .one()
        )
        profile.last_auth_at = last_auth_at
        profile.last_auth_status = last_auth_status
        session.commit()


# ---------------------------------------------------------------------------
# _is_amazon_auth_expired
# ---------------------------------------------------------------------------


class TestIsAmazonAuthExpired:
    def test_is_amazon_auth_expired_returns_true_when_status_failed(self) -> None:
        # input
        now = datetime(2026, 5, 10, 12, 0, 0)
        profile = make_profile(
            last_auth_at=now - timedelta(days=1),
            last_auth_status="failed",
        )

        # act
        output = _is_amazon_auth_expired(profile, now=now)

        # assert
        assert output is True

    def test_is_amazon_auth_expired_returns_true_when_last_auth_at_is_none(
        self,
    ) -> None:
        # input
        now = datetime(2026, 5, 10, 12, 0, 0)
        profile = make_profile(last_auth_at=None, last_auth_status=None)

        # act
        output = _is_amazon_auth_expired(profile, now=now)

        # assert
        assert output is True

    def test_is_amazon_auth_expired_returns_false_for_recent_success(self) -> None:
        # input
        now = datetime(2026, 5, 10, 12, 0, 0)
        profile = make_profile(
            last_auth_at=now - timedelta(days=1),
            last_auth_status="success",
        )

        # act
        output = _is_amazon_auth_expired(profile, now=now)

        # assert
        assert output is False

    def test_is_amazon_auth_expired_returns_true_when_older_than_stale_window(
        self,
    ) -> None:
        # input
        now = datetime(2026, 5, 10, 12, 0, 0)
        profile = make_profile(
            last_auth_at=now - timedelta(days=_AMAZON_AUTH_STALE_DAYS + 1),
            last_auth_status="success",
        )

        # act
        output = _is_amazon_auth_expired(profile, now=now)

        # assert
        assert output is True

    def test_is_amazon_auth_expired_returns_false_at_stale_window_boundary(
        self,
    ) -> None:
        # Exactly 30 days old is NOT expired (the comparison is strict ``>``).
        # input
        now = datetime(2026, 5, 10, 12, 0, 0)
        profile = make_profile(
            last_auth_at=now - timedelta(days=_AMAZON_AUTH_STALE_DAYS),
            last_auth_status="success",
        )

        # act
        output = _is_amazon_auth_expired(profile, now=now)

        # assert
        assert output is False


# ---------------------------------------------------------------------------
# _build_amazon_auth_alert
# ---------------------------------------------------------------------------


class TestBuildAmazonAuthAlert:
    def test_build_amazon_auth_alert_returns_none_when_no_profiles(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)

        # act
        output = _build_amazon_auth_alert(db)

        # assert
        assert output is None

    def test_build_amazon_auth_alert_returns_none_when_all_profiles_healthy(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")
        set_profile_auth_state(
            db,
            profile_key="primary",
            last_auth_at=datetime.utcnow() - timedelta(days=1),
            last_auth_status="success",
        )

        # act
        output = _build_amazon_auth_alert(db)

        # assert
        assert output is None

    def test_build_amazon_auth_alert_ignores_disabled_profiles(
        self, tmp_path: Path
    ) -> None:
        # A disabled profile that *would* be expired must not produce an alert.
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="dormant", display_name="Dormant", enabled=False
        )
        set_profile_auth_state(
            db,
            profile_key="dormant",
            last_auth_at=None,
            last_auth_status=None,
        )

        # act
        output = _build_amazon_auth_alert(db)

        # assert
        assert output is None

    def test_build_amazon_auth_alert_returns_banner_for_expired_profile(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary Account"
        )
        set_profile_auth_state(
            db,
            profile_key="primary",
            last_auth_at=datetime.utcnow() - timedelta(days=2),
            last_auth_status="failed",
        )

        # act
        output = _build_amazon_auth_alert(db)

        # assert
        assert output is not None
        html, text = output
        assert "Primary Account (primary)" in html
        assert "Amazon login expired" in html
        assert "transactoid amazon-login refresh" in html
        assert "Primary Account (primary)" in text
        assert text.startswith("[ALERT] Amazon login expired:")

    def test_build_amazon_auth_alert_lists_multiple_expired_profiles(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", sort_order=0
        )
        db.create_amazon_login_profile(
            profile_key="secondary", display_name="Secondary", sort_order=1
        )
        set_profile_auth_state(
            db,
            profile_key="primary",
            last_auth_at=None,
            last_auth_status=None,
        )
        set_profile_auth_state(
            db,
            profile_key="secondary",
            last_auth_at=datetime.utcnow()
            - timedelta(days=_AMAZON_AUTH_STALE_DAYS + 5),
            last_auth_status="success",
        )

        # act
        output = _build_amazon_auth_alert(db)

        # assert
        assert output is not None
        html, text = output
        assert "Primary (primary), Secondary (secondary)" in html
        assert "Primary (primary), Secondary (secondary)" in text


# ---------------------------------------------------------------------------
# _inject_alert_html
# ---------------------------------------------------------------------------


class TestInjectAlertHtml:
    def test_inject_alert_html_inserts_after_body_tag(self) -> None:
        # input
        html_content = "<html><body><p>Report</p></body></html>"
        alert_html = '<div class="alert">!</div>'

        # act
        output = _inject_alert_html(html_content, alert_html)

        # assert
        expected_output = (
            '<html><body>\n<div class="alert">!</div><p>Report</p></body></html>'
        )
        assert output == expected_output

    def test_inject_alert_html_handles_body_tag_with_attributes(self) -> None:
        # input
        html_content = '<html><body class="report"><p>x</p></body></html>'
        alert_html = "<b>!</b>"

        # act
        output = _inject_alert_html(html_content, alert_html)

        # assert
        expected_output = '<html><body class="report">\n<b>!</b><p>x</p></body></html>'
        assert output == expected_output

    def test_inject_alert_html_prepends_when_no_body_tag(self) -> None:
        # input
        html_content = "<p>Just a fragment</p>"
        alert_html = "<b>!</b>"

        # act
        output = _inject_alert_html(html_content, alert_html)

        # assert
        expected_output = "<b>!</b><p>Just a fragment</p>"
        assert output == expected_output

    def test_inject_alert_html_matches_body_case_insensitively(self) -> None:
        # input
        html_content = "<HTML><BODY><P>x</P></BODY></HTML>"
        alert_html = "<b>!</b>"

        # act
        output = _inject_alert_html(html_content, alert_html)

        # assert
        expected_output = "<HTML><BODY>\n<b>!</b><P>x</P></BODY></HTML>"
        assert output == expected_output
