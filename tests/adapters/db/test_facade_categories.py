"""Tests for soft-delete (`deprecated_at`) behavior on the categories facade."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import (
    Category,
    CategoryRow,
    DerivedTransaction,
    PlaidTransaction,
    TransactionCategoryEvent,
)
from transactoid.taxonomy.core import CategoryNode, Taxonomy


def _create_db() -> DB:
    db = DB("sqlite:///:memory:")
    db.create_schema()
    return db


def _seed_baseline_categories(db: DB) -> None:
    """Insert a small two-level taxonomy via the seed helper (hard-replace)."""
    rows: list[CategoryRow] = [
        CategoryRow(
            category_id=1,
            parent_id=None,
            key="food",
            name="Food",
            description=None,
            parent_key=None,
            deprecated_at=None,
        ),
        CategoryRow(
            category_id=2,
            parent_id=1,
            key="food.groceries",
            name="Groceries",
            description=None,
            parent_key="food",
            deprecated_at=None,
        ),
        CategoryRow(
            category_id=3,
            parent_id=1,
            key="food.coffee",
            name="Coffee",
            description=None,
            parent_key="food",
            deprecated_at=None,
        ),
    ]
    db.replace_categories_rows(rows)


def _build_taxonomy(keys: list[tuple[str, str | None]]) -> Taxonomy:
    """Build a Taxonomy from (key, parent_key) tuples — names mirror keys."""
    nodes = [
        CategoryNode(key=key, name=key, description=None, parent_key=parent_key)
        for key, parent_key in keys
    ]
    return Taxonomy.from_nodes(nodes)


def _fetch_category_by_key(db: DB, key: str) -> Category | None:
    with db.session() as session:
        cat = session.query(Category).filter(Category.key == key).first()
        if cat is not None:
            session.expunge(cat)
        return cat


def test_replace_categories_from_taxonomy_deprecates_missing_keys() -> None:
    db = _create_db()
    _seed_baseline_categories(db)
    new_taxonomy = _build_taxonomy([("food", None), ("food.groceries", "food")])

    db.replace_categories_from_taxonomy(new_taxonomy)

    coffee = _fetch_category_by_key(db, "food.coffee")
    groceries = _fetch_category_by_key(db, "food.groceries")
    food = _fetch_category_by_key(db, "food")
    assert coffee is not None and coffee.deprecated_at is not None
    assert groceries is not None and groceries.deprecated_at is None
    assert food is not None and food.deprecated_at is None


def test_replace_categories_from_taxonomy_resurrects_deprecated_key() -> None:
    db = _create_db()
    _seed_baseline_categories(db)
    deprecated_taxonomy = _build_taxonomy([("food", None), ("food.groceries", "food")])
    db.replace_categories_from_taxonomy(deprecated_taxonomy)

    deprecated_coffee = _fetch_category_by_key(db, "food.coffee")
    assert deprecated_coffee is not None and deprecated_coffee.deprecated_at is not None
    deprecated_id = deprecated_coffee.category_id

    revived_taxonomy = _build_taxonomy(
        [("food", None), ("food.groceries", "food"), ("food.coffee", "food")]
    )
    db.replace_categories_from_taxonomy(revived_taxonomy)

    resurrected = _fetch_category_by_key(db, "food.coffee")
    assert resurrected is not None
    assert resurrected.category_id == deprecated_id
    assert resurrected.deprecated_at is None


def test_get_category_id_by_key_excludes_deprecated() -> None:
    db = _create_db()
    _seed_baseline_categories(db)
    db.replace_categories_from_taxonomy(
        _build_taxonomy([("food", None), ("food.groceries", "food")])
    )

    output = db.get_category_id_by_key("food.coffee")

    assert output is None


def test_resolve_category_keys_includes_deprecated() -> None:
    db = _create_db()
    _seed_baseline_categories(db)
    db.replace_categories_from_taxonomy(
        _build_taxonomy([("food", None), ("food.groceries", "food")])
    )
    coffee = _fetch_category_by_key(db, "food.coffee")
    assert coffee is not None and coffee.deprecated_at is not None

    with db.session() as session:
        output = db._resolve_category_keys(session, {coffee.category_id})

    assert output == {coffee.category_id: "food.coffee"}


def test_partial_unique_allows_deprecated_key_collision() -> None:
    db = _create_db()
    _seed_baseline_categories(db)
    db.replace_categories_from_taxonomy(
        _build_taxonomy([("food", None), ("food.groceries", "food")])
    )

    # food.coffee is now deprecated; inserting another active row with the
    # same key must succeed under the partial unique index.
    with db.session() as session:
        session.add(
            Category(
                key="food.coffee",
                name="Coffee 2",
                description=None,
                parent_id=None,
                deprecated_at=None,
            )
        )
        session.flush()

    # Adding a *second* active row with the same key must fail.
    with pytest.raises(IntegrityError), db.session() as session:
        session.add(
            Category(
                key="food.coffee",
                name="Coffee 3",
                description=None,
                parent_id=None,
                deprecated_at=None,
            )
        )
        session.flush()


def test_replace_categories_from_taxonomy_succeeds_with_audit_events() -> None:
    """A category referenced by transaction_category_events deprecates cleanly."""
    db = _create_db()
    _seed_baseline_categories(db)

    # Wire a real transaction + audit event pointing at food.coffee so a
    # naive DELETE would fail with a FK violation.
    with db.session() as session:
        plaid_txn = PlaidTransaction(
            external_id="ext_1",
            source="PLAID",
            account_id="acct_1",
            posted_at=date(2026, 1, 1),
            amount_cents=500,
            currency="USD",
            merchant_descriptor="Test Coffee",
            institution=None,
        )
        session.add(plaid_txn)
        session.flush()
        derived = DerivedTransaction(
            plaid_transaction_id=plaid_txn.plaid_transaction_id,
            external_id="ext_1",
            posted_at=date(2026, 1, 1),
            amount_cents=500,
            merchant_descriptor="Test Coffee",
            merchant_id=None,
            category_id=2,  # food.groceries
            category_model="gpt-5.2",
            category_method="taxonomy_migration",
            category_assigned_at=datetime.now(),
            is_verified=False,
        )
        session.add(derived)
        session.flush()
        session.add(
            TransactionCategoryEvent(
                transaction_id=derived.transaction_id,
                from_category_id=3,  # food.coffee — about to be deprecated
                to_category_id=2,
                from_category_key="food.coffee",
                to_category_key="food.groceries",
                method="taxonomy_migration",
                model=None,
                reason="test_setup",
                created_at=datetime.now(),
            )
        )
        session.flush()

    db.replace_categories_from_taxonomy(
        _build_taxonomy([("food", None), ("food.groceries", "food")])
    )

    coffee = _fetch_category_by_key(db, "food.coffee")
    assert coffee is not None and coffee.deprecated_at is not None
