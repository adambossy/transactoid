"""Fast-path (exact verified match) test for the per-transaction categorizer.

Verifies that ``categorize_one`` reuses an existing verified categorization for an
exact merchant descriptor at confidence 1.0, marks the new row verified, and never
invokes the LLM agent.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, DerivedTransaction, PlaidTransaction
from penny.taxonomy import loader as taxonomy_loader
from penny.tools._services import categorizer_agent


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _seed_category(db: DB, key: str, name: str) -> int:
    with db.session() as session:
        cat = Category(key=key, name=name)
        session.add(cat)
        session.flush()
        return int(cat.category_id)


def _seed_txn(
    db: DB,
    *,
    external_id: str,
    descriptor: str,
    category_id: int | None = None,
    is_verified: bool = False,
) -> int:
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
        has_cat = category_id is not None
        txn = DerivedTransaction(
            plaid_transaction_id=plaid.plaid_transaction_id,
            external_id=external_id,
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
            merchant_descriptor=descriptor,
            category_id=category_id,
            category_method="manual" if has_cat else None,
            category_assigned_at=datetime(2026, 1, 10, 12, 0, 0) if has_cat else None,
            is_verified=is_verified,
        )
        session.add(txn)
        session.flush()
        return int(txn.transaction_id)


async def test_categorize_one_fast_path_reuses_verified_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taxonomy_loader._category_id_cache.clear()
    db = _create_db(tmp_path)
    groceries = _seed_category(db, "fastpath.groceries", "Groceries")
    # A prior VERIFIED categorization for this exact descriptor.
    _seed_txn(
        db,
        external_id="verified-1",
        descriptor="TRADER JOES #42",
        category_id=groceries,
        is_verified=True,
    )
    # The new, uncategorized row to be decided.
    new_id = _seed_txn(db, external_id="new-1", descriptor="TRADER JOES #42")

    # Wire the module globals to the test DB; taxonomy is unused by get_category_id.
    monkeypatch.setattr(categorizer_agent, "get_db", lambda: db)
    monkeypatch.setattr(categorizer_agent, "get_taxonomy", lambda: None)

    # The agent must NOT be built/run on the fast path.
    def _fail() -> None:
        raise AssertionError("agent should not be invoked on the fast path")

    monkeypatch.setattr(categorizer_agent, "build_categorizer_agent", _fail)

    decision = await categorizer_agent.categorize_one(
        {"transaction_id": new_id, "merchant_descriptor": "TRADER JOES #42"}
    )

    assert decision["method"] == "fast_path"
    assert decision["category_key"] == "fastpath.groceries"
    assert decision["confidence"] == 1.0

    # The new row is now categorized AND verified.
    with db.session() as session:
        row = (
            session.query(DerivedTransaction)
            .filter(DerivedTransaction.transaction_id == new_id)
            .one()
        )
        assert row.category_id == groceries
        assert row.is_verified is True


async def test_categorize_one_no_match_falls_through_to_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taxonomy_loader._category_id_cache.clear()
    db = _create_db(tmp_path)
    new_id = _seed_txn(db, external_id="new-1", descriptor="MYSTERY VENDOR XYZ")

    monkeypatch.setattr(categorizer_agent, "get_db", lambda: db)

    invoked = {"ran": False}

    class _StubAgent:
        async def run(self, prompt: str) -> None:  # noqa: ARG002
            invoked["ran"] = True

    monkeypatch.setattr(
        categorizer_agent, "build_categorizer_agent", lambda: _StubAgent()
    )

    decision = await categorizer_agent.categorize_one(
        {"transaction_id": new_id, "merchant_descriptor": "MYSTERY VENDOR XYZ"}
    )

    # No verified match -> the agent path runs. The stub doesn't persist, so the
    # decision is the "agent did not submit" sentinel; the key assertion is that we
    # did fall through to the agent rather than fast-pathing.
    assert invoked["ran"] is True
    assert decision["method"] == "agent"
