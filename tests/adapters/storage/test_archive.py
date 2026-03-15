"""Tests for archive_investment_dupes_to_r2."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

from transactoid.adapters.storage.archive import archive_investment_dupes_to_r2
from transactoid.adapters.storage.r2 import R2StorageError


class TestArchiveInvestmentDupesToR2:
    """Tests for the standalone archival function."""

    def test_uploads_with_correct_key_prefix(self) -> None:
        """R2 key uses the provided prefix and item_id."""
        # input
        records: list[dict[str, Any]] = [
            {"external_id": "inv-1", "posted_at": date(2026, 2, 15)}
        ]

        # act
        with patch(
            "transactoid.adapters.storage.archive.store_object_in_r2"
        ) as mock_store:
            archive_investment_dupes_to_r2(
                item_id="item-123",
                records=records,
                key_prefix="test-prefix",
            )

        # assert
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args.kwargs
        assert call_kwargs["key"].startswith("test-prefix/item-123/")
        assert call_kwargs["key"].endswith(".json")
        assert call_kwargs["content_type"] == "application/json"

    def test_graceful_r2_failure(self) -> None:
        """R2 failure is swallowed with a warning, not raised."""
        # input
        records: list[dict[str, Any]] = [{"external_id": "inv-1"}]

        # act — should not raise
        with patch(
            "transactoid.adapters.storage.archive.store_object_in_r2",
            side_effect=R2StorageError("boom"),
        ):
            archive_investment_dupes_to_r2(
                item_id="item-123",
                records=records,
            )

    def test_serializes_date_values(self) -> None:
        """Date values in records are converted to ISO format strings."""
        import json

        # input
        records: list[dict[str, Any]] = [
            {"posted_at": date(2026, 2, 15), "amount_cents": 5000}
        ]

        # act
        with patch(
            "transactoid.adapters.storage.archive.store_object_in_r2"
        ) as mock_store:
            archive_investment_dupes_to_r2(
                item_id="item-123",
                records=records,
            )

        # assert
        body_bytes = mock_store.call_args.kwargs["body"]
        payload = json.loads(body_bytes)
        assert payload[0]["posted_at"] == "2026-02-15"
        assert payload[0]["amount_cents"] == 5000
