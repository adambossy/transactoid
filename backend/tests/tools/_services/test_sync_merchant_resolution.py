"""SyncTool wires the merchant normalizer into the sync path.

_resolve_merchant_ids (async) normalizes descriptors and upserts merchants;
_mutate_batch_to_derived stamps the resolved merchant_id onto 1:1 payloads.
A fake normalizer is injected so these run without any LLM/network.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from penny.adapters.db.facade import DB
from penny.adapters.db.models import DerivedTransaction, Merchant
from penny.normalizer import NormalizedMerchant
from penny.tools._services.sync_service import SyncTool


class _FakeNormalizer:
    """Deterministic stand-in for MerchantNormalizer (no LLM)."""

    def __init__(self, mapping: dict[str, NormalizedMerchant]) -> None:
        self._mapping = mapping

    async def normalize_many(
        self, descriptors: list[str]
    ) -> dict[str, NormalizedMerchant]:
        return {d: self._mapping[d] for d in descriptors if d in self._mapping}


def _db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}", enforce_sqlite_fks=True)
    db.create_schema()
    return db


def _sync_tool(db: DB, normalizer: object) -> SyncTool:
    tool = SyncTool(
        plaid_client=MagicMock(),
        categorizer_factory=MagicMock(),
        db=db,
        taxonomy=MagicMock(),
    )
    tool._normalizer = normalizer  # type: ignore[assignment]
    return tool


def _insert_plaid(
    db: DB,
    *,
    external_id: str,
    merchant_descriptor: str,
    original_descriptor: str | None,
) -> int:
    txn = db.upsert_plaid_transaction(
        external_id=external_id,
        source="PLAID",
        account_id="acct-1",
        posted_at=date(2026, 3, 1),
        amount_cents=8000,
        currency="USD",
        merchant_descriptor=merchant_descriptor,
        institution=None,
        original_descriptor=original_descriptor,
    )
    return txn.plaid_transaction_id


def _derived_merchant(db: DB, plaid_id: int) -> Merchant:
    with db.session() as session:
        row = (
            session.query(DerivedTransaction)
            .filter_by(plaid_transaction_id=plaid_id)
            .one()
        )
        merchant = session.query(Merchant).filter_by(merchant_id=row.merchant_id).one()
        session.expunge(merchant)
    return merchant


async def test_venmo_resolves_to_counterparty_via_original_descriptor(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    db.set_sign_convention("acct-1", "expense_positive")
    # merchant_descriptor collapses to "Venmo"; the person is in original_descriptor.
    plaid_id = _insert_plaid(
        db,
        external_id="venmo-1",
        merchant_descriptor="Venmo",
        original_descriptor='Jonah Spear "🏠 :venmo_dollar: 🎁"',
    )
    # Input selection picks original_descriptor for the bare "Venmo" label.
    normalizer = _FakeNormalizer(
        {
            'Jonah Spear "🏠 :venmo_dollar: 🎁"': NormalizedMerchant(
                normalized_name="venmo:jonah-spear",
                display_name="Venmo: Jonah Spear",
                source_channel="venmo",
                counterparty="Jonah Spear",
            )
        }
    )
    tool = _sync_tool(db, normalizer)

    merchant_ids = await tool._resolve_merchant_ids([plaid_id])
    tool._mutate_batch_to_derived([plaid_id], merchant_ids)

    merchant = _derived_merchant(db, plaid_id)
    assert merchant.normalized_name == "venmo:jonah-spear"
    assert merchant.source_channel == "venmo"
    assert merchant.counterparty == "Jonah Spear"


async def test_direct_merchant_keeps_cleaned_name(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.set_sign_convention("acct-1", "expense_positive")
    plaid_id = _insert_plaid(
        db,
        external_id="amzn-1",
        merchant_descriptor="Amazon",
        original_descriptor="AMZN MKTP US*2X4AB AMZN.COM/BILL WA",
    )
    # Direct merchant: input selection keeps "Amazon" (not the raw text).
    normalizer = _FakeNormalizer(
        {
            "Amazon": NormalizedMerchant(
                normalized_name="amazon",
                display_name="Amazon",
                source_channel="direct",
                counterparty=None,
            )
        }
    )
    tool = _sync_tool(db, normalizer)

    merchant_ids = await tool._resolve_merchant_ids([plaid_id])
    tool._mutate_batch_to_derived([plaid_id], merchant_ids)

    merchant = _derived_merchant(db, plaid_id)
    assert merchant.normalized_name == "amazon"
    assert merchant.source_channel == "direct"
    assert merchant.counterparty is None


def test_legacy_path_without_map_still_resolves_merchant(tmp_path: Path) -> None:
    # Sync callers (re-derive / remutate / tests) pass no map; the facade
    # resolves the merchant the legacy (naive) way.
    db = _db(tmp_path)
    db.set_sign_convention("acct-1", "expense_positive")
    plaid_id = _insert_plaid(
        db,
        external_id="legacy-1",
        merchant_descriptor="Sweetgreen 123",
        original_descriptor=None,
    )
    tool = _sync_tool(db, _FakeNormalizer({}))

    tool._mutate_batch_to_derived([plaid_id])  # no map

    merchant = _derived_merchant(db, plaid_id)
    # naive: lowercase, digits stripped, whitespace collapsed + trimmed
    assert merchant.normalized_name == "sweetgreen"
    assert merchant.source_channel is None  # legacy path sets no channel
