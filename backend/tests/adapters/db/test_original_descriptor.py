"""original_descriptor is captured from Plaid and persisted (Tier 2.5).

Plaid's raw issuer description (their field: ``original_description``) carries
counterparty detail that merchant_descriptor drops for wrapper merchants (e.g.
the person behind a Venmo payment). We store it internally as
``original_descriptor`` to match ``merchant_descriptor``. These cover the client
mapping and the persistence path.
"""

from __future__ import annotations

from datetime import date

import pytest

from penny.adapters.clients.plaid import PlaidTransactionModel
from penny.db import get_db


def test_plaid_model_to_typed_maps_plaid_field_to_internal_name() -> None:
    # Plaid's wire field is original_description; to_typed exposes it as
    # original_descriptor internally.
    model = PlaidTransactionModel(
        transaction_id="t1",
        account_id="acct",
        amount=80.0,
        date="2025-08-31",
        name="Venmo",
        merchant_name=None,
        original_description='Jenny O\'Leary ":venmo_dollar:"',
    )
    typed = model.to_typed()
    assert typed["original_descriptor"] == 'Jenny O\'Leary ":venmo_dollar:"'
    # merchant-name/name still collapse to the bare label — hence the need.
    assert typed["name"] == "Venmo"


def test_to_typed_defaults_original_descriptor_to_none() -> None:
    model = PlaidTransactionModel(
        transaction_id="t2",
        account_id="acct",
        amount=5.0,
        date="2025-01-01",
        name="Sweetgreen",
    )
    assert model.to_typed()["original_descriptor"] is None


def test_upsert_plaid_transaction_persists_original_descriptor(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    txn = get_db().upsert_plaid_transaction(
        external_id="ext-venmo-1",
        source="PLAID",
        account_id="acct-venmo",
        posted_at=date(2025, 8, 31),
        amount_cents=8000,
        currency="USD",
        merchant_descriptor="Venmo",
        institution="Venmo - Personal",
        original_descriptor='Jenny O\'Leary ":venmo_dollar:"',
    )
    fetched = get_db().get_plaid_transaction(txn.plaid_transaction_id)
    assert fetched is not None
    assert fetched.merchant_descriptor == "Venmo"
    assert fetched.original_descriptor == 'Jenny O\'Leary ":venmo_dollar:"'


def test_upsert_updates_original_descriptor_on_conflict(
    isolated_db: pytest.FixtureRequest,
) -> None:
    get_db().create_schema()
    first = get_db().upsert_plaid_transaction(
        external_id="ext-venmo-2",
        source="PLAID",
        account_id="acct",
        posted_at=date(2025, 1, 1),
        amount_cents=1000,
        currency="USD",
        merchant_descriptor="Venmo",
        institution=None,
        original_descriptor=None,
    )
    # A re-sync now supplies the raw description.
    get_db().upsert_plaid_transaction(
        external_id="ext-venmo-2",
        source="PLAID",
        account_id="acct",
        posted_at=date(2025, 1, 1),
        amount_cents=1000,
        currency="USD",
        merchant_descriptor="Venmo",
        institution=None,
        original_descriptor="Keela Williams",
    )
    fetched = get_db().get_plaid_transaction(first.plaid_transaction_id)
    assert fetched is not None
    assert fetched.original_descriptor == "Keela Williams"
