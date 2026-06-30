"""Tests for the end-of-sync categorization sweep + advisory lock.

Covers per-descriptor dedup (one agent run per unique merchant descriptor, with
siblings reusing the decision) and the SQLite no-op advisory lock.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, DerivedTransaction, PlaidTransaction
from penny.taxonomy import loader as taxonomy_loader
from penny.tools._services.sync_service import SyncTool


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}", enforce_sqlite_fks=True)
    db.create_schema()
    return db


def _sync_tool(db: DB) -> SyncTool:
    return SyncTool(
        plaid_client=MagicMock(),
        categorizer_factory=MagicMock(),
        db=db,
        taxonomy=MagicMock(),
    )


def _seed_category(db: DB, key: str, name: str) -> int:
    with db.session() as session:
        cat = Category(key=key, name=name)
        session.add(cat)
        session.flush()
        return int(cat.category_id)


def _seed_txn(db: DB, *, external_id: str, descriptor: str) -> int:
    with db.session() as session:
        plaid = PlaidTransaction(
            external_id=f"plaid-{external_id}",
            source="PLAID",
            account_id="acct-1",
            item_id=None,
            posted_at=date(2026, 1, 10),
            amount_cents=5000,
            currency="USD",
        )
        session.add(plaid)
        session.flush()
        txn = DerivedTransaction(
            plaid_transaction_id=plaid.plaid_transaction_id,
            external_id=external_id,
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
            merchant_descriptor=descriptor,
        )
        session.add(txn)
        session.flush()
        return int(txn.transaction_id)


async def test_sweep_dedups_by_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taxonomy_loader._category_id_cache.clear()
    db = _create_db(tmp_path)
    groceries = _seed_category(db, "sweep.groceries", "Groceries")
    # Three rows share a descriptor; one is unique.
    for ext in ("a1", "a2", "a3"):
        _seed_txn(db, external_id=ext, descriptor="ACME")
    _seed_txn(db, external_id="z1", descriptor="ZED")

    calls: list[str] = []

    async def fake_categorize_one(txn: dict) -> dict:
        calls.append(txn["merchant_descriptor"])
        # Mimic the agent persisting the first row of the group.
        db.update_derived_mutable(
            txn["transaction_id"],
            {
                "category_id": groceries,
                "category_method": "llm",
                "category_reason": "agent: groceries",
            },
        )
        return {
            "transaction_id": txn["transaction_id"],
            "category_key": "sweep.groceries",
            "reasoning": "agent: groceries",
        }

    monkeypatch.setattr(
        "penny.tools._services.categorizer_agent.categorize_one", fake_categorize_one
    )
    monkeypatch.setattr("penny.services.get_taxonomy", lambda: MagicMock())

    tool = _sync_tool(db)
    await tool._categorize_uncategorized()

    # One agent run per unique descriptor (not one per row).
    assert sorted(calls) == ["ACME", "ZED"]

    # Every row ended up categorized (siblings reused the decision).
    with db.session() as session:
        cats = [t.category_id for t in session.query(DerivedTransaction).all()]
    assert cats == [groceries] * 4


def test_advisory_lock_is_noop_on_sqlite(tmp_path: Path) -> None:
    db = _create_db(tmp_path)
    with db.try_advisory_lock(12345) as acquired:
        assert acquired is True
