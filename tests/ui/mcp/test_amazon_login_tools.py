"""Tests for MCP Amazon login management tool functions.

Each test calls the underlying Python function directly by patching the
module-level ``db`` global with a real SQLite test database. This verifies
the contract (input -> output shape) without going through the MCP wire
protocol.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from transactoid.adapters.db.facade import DB
import transactoid.ui.mcp.server as mcp_server
from transactoid.ui.mcp.server import (
    add_amazon_login,
    clear_amazon_login_context,
    disable_amazon_login,
    enable_amazon_login,
    list_amazon_logins,
    remove_amazon_login,
    update_amazon_login,
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


# ---------------------------------------------------------------------------
# list_amazon_logins
# ---------------------------------------------------------------------------


class TestListAmazonLogins:
    def test_list_amazon_logins_returns_empty_profiles_list(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = list_amazon_logins()

        # assert
        assert result == {"profiles": []}

    def test_list_amazon_logins_returns_all_profiles(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary Account", sort_order=0
        )
        db.create_amazon_login_profile(
            profile_key="secondary", display_name="Secondary Account", sort_order=1
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = list_amazon_logins()

        # assert
        assert len(result["profiles"]) == 2
        keys = {p["profile_key"] for p in result["profiles"]}
        assert keys == {"primary", "secondary"}

    def test_list_amazon_logins_profile_shape(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary Account"
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = list_amazon_logins()

        # expected shape
        required_keys = {
            "profile_key",
            "display_name",
            "enabled",
            "sort_order",
            "has_context",
            "last_auth_status",
            "last_auth_at",
        }

        # assert
        assert len(result["profiles"]) == 1
        assert required_keys.issubset(result["profiles"][0].keys())

    def test_list_amazon_logins_has_context_false_when_no_context_id(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")

        with patch.object(mcp_server, "db", db):
            result = list_amazon_logins()

        assert result["profiles"][0]["has_context"] is False

    def test_list_amazon_logins_has_context_true_when_context_id_set(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")
        db.set_amazon_login_context_id(profile_key="primary", context_id="ctx-abc-123")

        with patch.object(mcp_server, "db", db):
            result = list_amazon_logins()

        assert result["profiles"][0]["has_context"] is True


# ---------------------------------------------------------------------------
# add_amazon_login
# ---------------------------------------------------------------------------


class TestAddAmazonLogin:
    def test_add_amazon_login_creates_profile(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = add_amazon_login(
                profile_key="primary",
                display_name="Primary Account",
            )

        # expected
        expected = {
            "status": "success",
            "profile_key": "primary",
            "display_name": "Primary Account",
            "message": "Created profile 'primary'",
        }

        # assert
        assert result == expected

    def test_add_amazon_login_persists_to_db(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            add_amazon_login(
                profile_key="primary",
                display_name="Primary Account",
            )

        # assert: profile is retrievable from the DB
        profiles = db.list_amazon_login_profiles()
        assert len(profiles) == 1
        assert profiles[0].profile_key == "primary"

    def test_add_amazon_login_duplicate_key_returns_error(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="First")

        with patch.object(mcp_server, "db", db):
            # act
            result = add_amazon_login(
                profile_key="primary",
                display_name="Duplicate",
            )

        # assert: error returned, not exception raised
        assert result["status"] == "error"
        assert "message" in result

    def test_add_amazon_login_respects_enabled_flag(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            add_amazon_login(
                profile_key="disabled-profile",
                display_name="Disabled",
                enabled=False,
            )

        profiles = db.list_amazon_login_profiles()
        assert profiles[0].enabled is False

    def test_add_amazon_login_respects_sort_order(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            add_amazon_login(
                profile_key="primary",
                display_name="Primary",
                sort_order=5,
            )

        profiles = db.list_amazon_login_profiles()
        assert profiles[0].sort_order == 5


# ---------------------------------------------------------------------------
# update_amazon_login
# ---------------------------------------------------------------------------


class TestUpdateAmazonLogin:
    def test_update_amazon_login_no_fields_returns_error(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")

        with patch.object(mcp_server, "db", db):
            # act — no optional fields provided
            result = update_amazon_login(profile_key="primary")

        # assert: validation error returned without exception
        assert result["status"] == "error"
        assert "at least one" in result["message"].lower()

    def test_update_amazon_login_display_name_succeeds(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Old Name")

        with patch.object(mcp_server, "db", db):
            # act
            result = update_amazon_login(profile_key="primary", display_name="New Name")

        # assert
        assert result["status"] == "success"
        assert result["profile_key"] == "primary"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.display_name == "New Name"

    def test_update_amazon_login_enabled_flag_succeeds(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", enabled=True
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = update_amazon_login(profile_key="primary", enabled=False)

        # assert
        assert result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.enabled is False

    def test_update_amazon_login_sort_order_succeeds(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", sort_order=0
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = update_amazon_login(profile_key="primary", sort_order=10)

        # assert
        assert result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.sort_order == 10

    def test_update_amazon_login_missing_profile_returns_error(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = update_amazon_login(
                profile_key="nonexistent", display_name="Doesn't matter"
            )

        # assert: error returned without exception
        assert result["status"] == "error"
        assert "message" in result


# ---------------------------------------------------------------------------
# remove_amazon_login
# ---------------------------------------------------------------------------


class TestRemoveAmazonLogin:
    def test_remove_amazon_login_existing_returns_success(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")

        with patch.object(mcp_server, "db", db):
            # act
            result = remove_amazon_login(profile_key="primary")

        # assert
        assert result["status"] == "success"
        assert "primary" in result["message"]

    def test_remove_amazon_login_existing_deletes_from_db(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")

        with patch.object(mcp_server, "db", db):
            remove_amazon_login(profile_key="primary")

        # assert: profile gone from DB
        profiles = db.list_amazon_login_profiles()
        assert profiles == []

    def test_remove_amazon_login_missing_returns_error(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = remove_amazon_login(profile_key="nonexistent")

        # assert: error returned without exception
        assert result["status"] == "error"
        assert "message" in result


# ---------------------------------------------------------------------------
# clear_amazon_login_context
# ---------------------------------------------------------------------------


class TestClearAmazonLoginContext:
    def test_clear_amazon_login_context_clears_stored_context(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")
        db.set_amazon_login_context_id(profile_key="primary", context_id="ctx-abc-123")

        with patch.object(mcp_server, "db", db):
            # act
            result = clear_amazon_login_context(profile_key="primary")

        # assert
        assert result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.browserbase_context_id is None

    def test_clear_amazon_login_context_already_none_succeeds(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(profile_key="primary", display_name="Primary")

        with patch.object(mcp_server, "db", db):
            # act
            result = clear_amazon_login_context(profile_key="primary")

        # assert: idempotent — already None is not an error
        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# enable_amazon_login / disable_amazon_login
# ---------------------------------------------------------------------------


class TestEnableDisableAmazonLogin:
    def test_enable_amazon_login_sets_enabled_true(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", enabled=False
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = enable_amazon_login(profile_key="primary")

        # assert
        assert result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.enabled is True

    def test_enable_amazon_login_missing_profile_returns_error(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = enable_amazon_login(profile_key="nonexistent")

        # assert
        assert result["status"] == "error"
        assert "message" in result

    def test_disable_amazon_login_sets_enabled_false(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", enabled=True
        )

        with patch.object(mcp_server, "db", db):
            # act
            result = disable_amazon_login(profile_key="primary")

        # assert
        assert result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.enabled is False

    def test_disable_amazon_login_missing_profile_returns_error(
        self, tmp_path: Path
    ) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = disable_amazon_login(profile_key="nonexistent")

        # assert
        assert result["status"] == "error"
        assert "message" in result

    def test_enable_then_disable_roundtrip(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.create_amazon_login_profile(
            profile_key="primary", display_name="Primary", enabled=False
        )

        with patch.object(mcp_server, "db", db):
            enable_result = enable_amazon_login(profile_key="primary")
            disable_result = disable_amazon_login(profile_key="primary")

        # assert
        assert enable_result["status"] == "success"
        assert disable_result["status"] == "success"
        profile = db.get_amazon_login_profile(profile_key="primary")
        assert profile is not None
        assert profile.enabled is False
