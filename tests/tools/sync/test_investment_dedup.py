"""Tests for investment transaction cross-source dedup."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

from transactoid.tools.sync.sync_tool import SyncTool

_R2_PATCH = "transactoid.adapters.storage.r2.store_object_in_r2"


def _make_plaid_item(
    item_id: str = "item-1",
    *,
    investments_synced_through: date | None = None,
) -> MagicMock:
    """Create a mock PlaidItem."""
    item = MagicMock()
    item.item_id = item_id
    item.access_token = "test-access-token"  # noqa: S105
    item.investments_synced_through = investments_synced_through
    return item


def _make_inv_txn(
    inv_txn_id: str,
    account_id: str,
    amount: float,
    txn_date: str,
    name: str = "Some Transaction",
    txn_type: str = "cash",
    subtype: str | None = None,
) -> dict[str, Any]:
    """Build a raw Plaid investment transaction dict."""
    return {
        "investment_transaction_id": inv_txn_id,
        "account_id": account_id,
        "amount": amount,
        "date": txn_date,
        "name": name,
        "type": txn_type,
        "subtype": subtype,
        "security_id": None,
        "iso_currency_code": "USD",
    }


def _create_sync_tool(db: MagicMock) -> tuple[SyncTool, MagicMock]:
    """Create a SyncTool with mocked dependencies.

    Returns:
        Tuple of (SyncTool, plaid_client_mock).
    """
    plaid_client = MagicMock()
    categorizer_factory = MagicMock()
    taxonomy = MagicMock()
    tool = SyncTool(
        plaid_client=plaid_client,
        categorizer_factory=categorizer_factory,
        db=db,
        taxonomy=taxonomy,
    )
    return tool, plaid_client


def _run_sync(
    sync_tool: SyncTool,
    item: MagicMock,
) -> tuple[int, int, int, str | None]:
    """Run _sync_investments_for_item synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(sync_tool._sync_investments_for_item(item))
    finally:
        loop.close()


class TestInvestmentDedup:
    """Tests for cross-source investment dedup."""

    def test_skips_when_plaid_match_exists(self) -> None:
        """Investment txns matching PLAID rows are skipped."""
        # input
        inv_txn = _make_inv_txn("inv-1", "acct-1", 50.0, "2026-01-15")
        item = _make_plaid_item(
            investments_synced_through=date(2026, 1, 10),
        )

        # setup
        db = MagicMock()
        sync_tool, plaid_mock = _create_sync_tool(db)
        plaid_mock.get_investment_transactions.return_value = {
            "investment_transactions": [inv_txn],
            "securities": [],
            "total_investment_transactions": 1,
        }
        natural_key = (
            "item-1",
            "acct-1",
            date(2026, 1, 15),
            5000,
        )
        db.find_plaid_matches_for_investment_dedup.return_value = {
            natural_key,
        }

        # act
        with patch(_R2_PATCH) as mock_r2:
            added, excluded, deduped, err = _run_sync(sync_tool, item)

        # assert
        assert added == 0
        assert excluded == 0
        assert deduped == 1
        assert err is None
        db.bulk_upsert_plaid_transactions.assert_not_called()
        mock_r2.assert_called_once()

    def test_inserts_when_no_plaid_match(self) -> None:
        """Investment txns with no PLAID match proceed to insert."""
        # input
        inv_txn = _make_inv_txn("inv-2", "acct-1", 100.0, "2026-01-20")
        item = _make_plaid_item(
            investments_synced_through=date(2026, 1, 10),
        )

        # setup
        db = MagicMock()
        sync_tool, plaid_mock = _create_sync_tool(db)
        plaid_mock.get_investment_transactions.return_value = {
            "investment_transactions": [inv_txn],
            "securities": [],
            "total_investment_transactions": 1,
        }
        db.find_plaid_matches_for_investment_dedup.return_value = set()
        db.bulk_upsert_plaid_transactions.return_value = [42]
        db.get_derived_by_plaid_ids.return_value = {42: []}

        # act
        with patch(_R2_PATCH) as mock_r2:
            added, excluded, deduped, err = _run_sync(sync_tool, item)

        # assert
        assert added == 1
        assert deduped == 0
        assert err is None
        db.bulk_upsert_plaid_transactions.assert_called_once()
        db.bulk_insert_derived_transactions.assert_called_once()
        mock_r2.assert_not_called()

    def test_batch_mixed(self) -> None:
        """Page with both duplicates and unique transactions."""
        # input
        dup_txn = _make_inv_txn("inv-dup", "acct-1", 75.0, "2026-02-01")
        unique_txn = _make_inv_txn(
            "inv-unique",
            "acct-1",
            200.0,
            "2026-02-05",
            txn_type="buy",
        )
        item = _make_plaid_item(
            investments_synced_through=date(2026, 1, 25),
        )

        # setup
        db = MagicMock()
        sync_tool, plaid_mock = _create_sync_tool(db)
        plaid_mock.get_investment_transactions.return_value = {
            "investment_transactions": [dup_txn, unique_txn],
            "securities": [],
            "total_investment_transactions": 2,
        }
        dup_key = ("item-1", "acct-1", date(2026, 2, 1), 7500)
        db.find_plaid_matches_for_investment_dedup.return_value = {
            dup_key,
        }
        db.bulk_upsert_plaid_transactions.return_value = [99]
        db.get_derived_by_plaid_ids.return_value = {99: []}

        # act
        with patch(_R2_PATCH) as mock_r2:
            added, excluded, deduped, err = _run_sync(sync_tool, item)

        # assert
        assert deduped == 1
        assert added == 0  # buy → DEFAULT_EXCLUDE
        assert excluded == 1
        db.bulk_upsert_plaid_transactions.assert_called_once()
        mock_r2.assert_called_once()


class TestArchiveInvestmentDupesToR2:
    """Tests for the R2 archival helper."""

    def test_correct_key_pattern(self) -> None:
        """Archive key matches expected pattern."""
        # setup
        db = MagicMock()
        sync_tool, _ = _create_sync_tool(db)
        raw_txn: dict[str, Any] = {
            "investment_transaction_id": "inv-1",
            "amount": 50.0,
        }
        normalized: dict[str, object] = {
            "external_id": "inv-1",
            "posted_at": date(2026, 1, 15),
            "amount_cents": 5000,
        }

        # act
        with patch(_R2_PATCH) as mock_r2:
            sync_tool._archive_investment_dupes_to_r2(
                "item-abc", [(raw_txn, normalized)]
            )

        # assert
        mock_r2.assert_called_once()
        call_kwargs = mock_r2.call_args[1]
        key = call_kwargs["key"]
        assert key.startswith("investment-dedup/item-abc/")
        assert key.endswith(".json")
        assert call_kwargs["content_type"] == "application/json"

    def test_swallows_r2_errors(self) -> None:
        """R2 upload failures are logged but do not raise."""
        from transactoid.adapters.storage.r2 import R2StorageError

        # setup
        db = MagicMock()
        sync_tool, _ = _create_sync_tool(db)
        raw_txn: dict[str, Any] = {
            "investment_transaction_id": "inv-1",
        }
        normalized: dict[str, object] = {
            "external_id": "inv-1",
            "posted_at": date(2026, 1, 15),
            "amount_cents": 5000,
        }

        # act — should not raise
        with patch(
            _R2_PATCH,
            side_effect=R2StorageError("boom"),
        ):
            sync_tool._archive_investment_dupes_to_r2(
                "item-abc", [(raw_txn, normalized)]
            )
