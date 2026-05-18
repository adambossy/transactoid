"""Tests for remutate_amazon_orders (Amazon backfill split orchestration)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.db.facade import DB
from transactoid.tools.amazon.remutate import (
    SupportsRemutation,
    remutate_amazon_orders,
)


class FakeRunner:
    """Stands in for SyncTool: records calls, returns canned derived ids."""

    def __init__(self, new_ids: list[int]) -> None:
        self._new_ids = new_ids
        self.mutate_calls: list[list[int]] = []
        self.categorize_calls: list[list[int]] = []

    def _mutate_batch_to_derived(self, plaid_ids: list[int]) -> list[int]:
        self.mutate_calls.append(list(plaid_ids))
        return list(self._new_ids)

    async def _categorize_derived(self, derived_ids: list[int]) -> None:
        self.categorize_calls.append(list(derived_ids))


def _exploding_factory(_db: DB) -> SupportsRemutation:
    raise AssertionError("sync_tool_factory must not be called on a dry run")


def create_test_db(tmp_path: Path) -> DB:
    """Create an isolated SQLite test database with schema."""
    db_path = tmp_path / "test.db"
    db = DB(f"sqlite:///{db_path}")
    db.create_schema()
    return db


def create_db_with_one_match(tmp_path: Path) -> tuple[DB, int]:
    """DB containing one Amazon order whose total matches one Plaid charge.

    Returns the db and the matched plaid_transaction_id.
    """
    db = create_test_db(tmp_path)
    profile = db.create_amazon_login_profile(
        profile_key="primary", display_name="Primary"
    )
    db.upsert_amazon_order(
        order_id="O1",
        order_date=date(2026, 1, 15),
        order_total_cents=4999,
        profile_id=profile.profile_id,
    )
    db.upsert_amazon_item(
        order_id="O1",
        asin="A1",
        description="Widget",
        price_cents=4999,
        quantity=1,
    )
    db.upsert_plaid_transaction(
        external_id="P1",
        source="PLAID",
        account_id="acct-1",
        posted_at=date(2026, 1, 20),
        amount_cents=4999,
        currency="USD",
        merchant_descriptor="AMAZON.COM",
        institution="Bank",
    )
    txns = db.list_plaid_transactions_in_date_range(
        start=date(2026, 1, 1), end=date(2026, 2, 1)
    )
    return db, txns[0].plaid_transaction_id


def _summary(result: dict[str, object]) -> dict[str, object]:
    """Project the result contract down to the fields under test."""
    return {
        "status": result["status"],
        "candidates": result["candidates"],
        "matched": result["matched"],
        "overwrites": result["overwrites"],
        "dry_run": result["dry_run"],
    }


def test_remutate_returns_noop_when_no_amazon_orders(tmp_path: Path) -> None:
    # input
    db = create_test_db(tmp_path)

    # act
    output = _summary(remutate_amazon_orders(db, dry_run=True))

    # expected
    expected_output = {
        "status": "noop",
        "candidates": 0,
        "matched": 0,
        "overwrites": 0,
        "dry_run": True,
    }

    # assert
    assert output == expected_output


def test_remutate_returns_noop_when_no_plaid_in_window(tmp_path: Path) -> None:
    # input
    db = create_test_db(tmp_path)
    profile = db.create_amazon_login_profile(
        profile_key="primary", display_name="Primary"
    )
    db.upsert_amazon_order(
        order_id="O1",
        order_date=date(2026, 1, 15),
        order_total_cents=4999,
        profile_id=profile.profile_id,
    )

    # act
    output = _summary(remutate_amazon_orders(db, dry_run=True))

    # expected
    expected_output = {
        "status": "noop",
        "candidates": 0,
        "matched": 0,
        "overwrites": 0,
        "dry_run": True,
    }

    # assert
    assert output == expected_output


def test_remutate_dry_run_reports_match_without_invoking_runner(
    tmp_path: Path,
) -> None:
    # input
    db, _plaid_id = create_db_with_one_match(tmp_path)

    # act — exploding factory proves the runner is never built on a dry run
    output = _summary(
        remutate_amazon_orders(db, dry_run=True, sync_tool_factory=_exploding_factory)
    )

    # expected
    expected_output = {
        "status": "dry_run",
        "candidates": 1,
        "matched": 1,
        "overwrites": 0,
        "dry_run": True,
    }

    # assert
    assert output == expected_output


def test_remutate_dry_run_flags_verified_overwrite(tmp_path: Path) -> None:
    # input
    db, plaid_id = create_db_with_one_match(tmp_path)
    db.bulk_insert_derived_transactions(
        [
            {
                "plaid_transaction_id": plaid_id,
                "external_id": "P1",
                "amount_cents": 4999,
                "posted_at": date(2026, 1, 20),
                "merchant_descriptor": "AMAZON.COM",
                "is_verified": True,
            }
        ]
    )

    # act
    result = remutate_amazon_orders(db, dry_run=True)
    output = {
        "summary": _summary(result),
        "overwrite_plaid_id": result["overwrite_details"][0]["plaid_transaction_id"],
        "overwrite_verified": result["overwrite_details"][0]["is_verified"],
    }

    # expected
    expected_output = {
        "summary": {
            "status": "dry_run",
            "candidates": 1,
            "matched": 1,
            "overwrites": 1,
            "dry_run": True,
        },
        "overwrite_plaid_id": plaid_id,
        "overwrite_verified": True,
    }

    # assert
    assert output == expected_output


def test_remutate_applies_split_and_categorizes(tmp_path: Path) -> None:
    # input
    db, plaid_id = create_db_with_one_match(tmp_path)
    fake = FakeRunner(new_ids=[101, 102])

    # act
    result = remutate_amazon_orders(
        db, dry_run=False, sync_tool_factory=lambda _db: fake
    )
    output = {
        "summary": _summary(result),
        "derived_after_split": result["derived_after_split"],
        "categorized": result["categorized"],
        "mutate_calls": fake.mutate_calls,
        "categorize_calls": fake.categorize_calls,
    }

    # expected
    expected_output = {
        "summary": {
            "status": "ok",
            "candidates": 1,
            "matched": 1,
            "overwrites": 0,
            "dry_run": False,
        },
        "derived_after_split": 2,
        "categorized": 2,
        "mutate_calls": [[plaid_id]],
        "categorize_calls": [[101, 102]],
    }

    # assert
    assert output == expected_output
