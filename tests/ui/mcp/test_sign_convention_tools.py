"""Smoke tests for MCP sign convention tool functions.

Each test calls the underlying Python function directly by patching the
module-level ``db`` global with a real SQLite test database.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
import transactoid.ui.mcp.server as mcp_server
from transactoid.ui.mcp.server import (
    list_sign_conventions,
    re_derive,
    set_sign_convention,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_test_db(tmp_path: Path) -> DB:
    """Create an isolated SQLite test database."""
    db = DB(f"sqlite:///{tmp_path / 'mcp_sign_conv.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(db: DB, *, account_id: str = "acct-m1") -> int:
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=f"pt-{account_id}",
            source="PLAID",
            account_id=account_id,
            item_id=None,
            posted_at=date(2026, 4, 1),
            amount_cents=1000,
            currency="USD",
        )
        session.add(txn)
        session.flush()
        plaid_id: int = txn.plaid_transaction_id
    return plaid_id


def _insert_derived_txn(db: DB, plaid_id: int, *, external_id: str = "dt-m1") -> None:
    with db.session() as session:
        row = DerivedTransaction(
            plaid_transaction_id=plaid_id,
            external_id=external_id,
            amount_cents=1000,
            posted_at=date(2026, 4, 1),
            is_verified=False,
        )
        session.add(row)


# ---------------------------------------------------------------------------
# set_sign_convention
# ---------------------------------------------------------------------------


class TestSetSignConvention:
    def test_set_sign_convention_success(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = set_sign_convention("acct-m1", "expense_negative")

        # expected
        expected_output = {
            "status": "success",
            "message": "Set account acct-m1 -> expense_negative",
        }

        # assert
        assert result == expected_output

    def test_set_sign_convention_invalid_convention(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = set_sign_convention("acct-m1", "bad_value")

        # assert
        assert result["status"] == "error"
        assert "expense_positive" in result["message"]
        assert "expense_negative" in result["message"]

    def test_set_sign_convention_with_notes(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = set_sign_convention(
                "acct-m2", "expense_positive", notes="Chase savings"
            )

        # assert
        assert result["status"] == "success"
        rows = db.list_sign_conventions()
        matching = [r for r in rows if r.account_id == "acct-m2"]
        assert len(matching) == 1
        assert matching[0].notes == "Chase savings"


# ---------------------------------------------------------------------------
# list_sign_conventions
# ---------------------------------------------------------------------------


class TestListSignConventions:
    def test_list_sign_conventions_empty(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            # act
            result = list_sign_conventions()

        # expected
        expected_output = {"status": "success", "conventions": [], "count": 0}

        # assert
        assert result == expected_output

    def test_list_sign_conventions_with_rows(self, tmp_path: Path) -> None:
        # input
        db = create_test_db(tmp_path)
        db.set_sign_convention("acct-a", "expense_positive", provenance="manual")
        db.set_sign_convention("acct-b", "expense_negative", provenance="seeded")

        with patch.object(mcp_server, "db", db):
            # act
            result = list_sign_conventions()

        # assert
        assert result["status"] == "success"
        assert result["count"] == 2
        keys = {c["account_id"] for c in result["conventions"]}
        assert keys == {"acct-a", "acct-b"}

    def test_list_sign_conventions_shape(self, tmp_path: Path) -> None:
        """Each convention dict has the expected keys."""
        db = create_test_db(tmp_path)
        db.set_sign_convention("acct-s", "expense_positive")

        with patch.object(mcp_server, "db", db):
            result = list_sign_conventions()

        assert result["count"] == 1
        conv = result["conventions"][0]
        assert set(conv.keys()) == {
            "account_id",
            "sign_convention",
            "provenance",
            "updated_at",
            "notes",
        }


# ---------------------------------------------------------------------------
# re_derive
# ---------------------------------------------------------------------------


class TestReDeriveToolSmoke:
    def test_re_derive_unknown_account(self, tmp_path: Path) -> None:
        """Non-existent account_id returns error status."""
        db = create_test_db(tmp_path)

        with patch.object(mcp_server, "db", db):
            result = re_derive("no-such-account")

        assert result["status"] == "error"
        assert "no-such-account" in result["message"]

    def test_re_derive_success(self, tmp_path: Path) -> None:
        """Existing account returns success with counts."""
        db = create_test_db(tmp_path)
        db.set_sign_convention("acct-rd-mcp", "expense_positive", provenance="manual")
        plaid_id = _insert_plaid_txn(db, account_id="acct-rd-mcp")
        _insert_derived_txn(db, plaid_id, external_id="dt-rd-mcp")

        class _StubRunner:
            def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
                new_ids: list[int] = []
                for pid in plaid_ids:
                    with db.session() as session:
                        row = DerivedTransaction(
                            plaid_transaction_id=pid,
                            external_id=f"new-mcp-{pid}",
                            amount_cents=1000,
                            posted_at=date(2026, 4, 1),
                            is_verified=False,
                        )
                        session.add(row)
                        session.flush()
                        new_ids.append(row.transaction_id)
                return new_ids

            async def _categorize_derived(self, derived_ids: list[int]) -> None:
                pass

        stub = _StubRunner()

        with patch.object(mcp_server, "db", db):
            with patch(
                "transactoid.services.re_derive._default_sync_tool",
                return_value=stub,
            ):
                result = re_derive("acct-rd-mcp")

        assert result["status"] == "success"
        assert result["re_derived"] == 1
        assert result["verified_skipped"] == 0
        assert result["account_id"] == "acct-rd-mcp"
