"""Tests for plaid-cleanup-investment-dupes CLI command."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from transactoid.adapters.db.models import PlaidTransaction
from transactoid.ui.cli import app

runner = CliRunner()


def _make_txn(
    *,
    external_id: str,
    item_id: str,
    posted_at: date,
    amount_cents: int,
    merchant_descriptor: str = "ATM Withdrawal",
) -> PlaidTransaction:
    """Build a detached PlaidTransaction for test assertions."""
    return PlaidTransaction(
        plaid_transaction_id=1,
        external_id=external_id,
        source="PLAID_INVESTMENT",
        account_id="acct-1",
        item_id=item_id,
        posted_at=posted_at,
        amount_cents=amount_cents,
        currency="USD",
        merchant_descriptor=merchant_descriptor,
        institution=None,
        created_at=datetime(2026, 2, 15),
        updated_at=datetime(2026, 2, 15),
    )


class TestPlaidCleanupInvestmentDupes:
    """Tests for the plaid-cleanup-investment-dupes command."""

    def test_no_duplicates_found(self) -> None:
        """Clean exit when no duplicates exist."""
        with patch("transactoid.ui.cli.DB") as mock_db_cls:
            mock_db = mock_db_cls.return_value
            mock_db.find_investment_dupes_with_plaid_match.return_value = []
            result = runner.invoke(app, ["plaid-cleanup-investment-dupes"])

        assert result.exit_code == 0
        assert "No duplicates found." in result.output

    def test_dry_run_prints_report(self) -> None:
        """Dry-run reports duplicates without deleting."""
        dupes = [
            _make_txn(
                external_id="inv-1",
                item_id="item-1",
                posted_at=date(2026, 2, 15),
                amount_cents=5000,
            ),
        ]

        with patch("transactoid.ui.cli.DB") as mock_db_cls:
            mock_db = mock_db_cls.return_value
            mock_db.find_investment_dupes_with_plaid_match.return_value = dupes
            result = runner.invoke(app, ["plaid-cleanup-investment-dupes"])

        assert result.exit_code == 0
        assert "Total duplicates: 1" in result.output
        assert "DRY RUN" in result.output
        mock_db.delete_plaid_transactions_by_external_ids.assert_not_called()

    def test_apply_archives_and_deletes(self) -> None:
        """--apply archives to R2 then deletes duplicates."""
        dupes = [
            _make_txn(
                external_id="inv-1",
                item_id="item-1",
                posted_at=date(2026, 2, 15),
                amount_cents=5000,
            ),
        ]

        with (
            patch("transactoid.ui.cli.DB") as mock_db_cls,
            patch(
                "transactoid.adapters.storage.archive.archive_investment_dupes_to_r2"
            ) as mock_archive,
        ):
            mock_db = mock_db_cls.return_value
            mock_db.find_investment_dupes_with_plaid_match.return_value = dupes
            mock_db.delete_plaid_transactions_by_external_ids.return_value = 1

            result = runner.invoke(app, ["plaid-cleanup-investment-dupes", "--apply"])

        assert result.exit_code == 0
        assert "Deleted 1 transactions for item item-1" in result.output

        mock_archive.assert_called_once()
        assert mock_archive.call_args.kwargs["key_prefix"] == "investment-dedup-cleanup"

        mock_db.delete_plaid_transactions_by_external_ids.assert_called_once_with(
            ["inv-1"], source="PLAID_INVESTMENT"
        )
