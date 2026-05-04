"""Tests for AmazonMutationPlugin: items writes and idempotency."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from transactoid.adapters.amazon.mutation_plugin import (
    AmazonMutationPlugin,
    AmazonMutationPluginConfig,
)
from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import (
    DerivedTransaction,
    PlaidTransaction,
    TransactionItem,
)


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema.

    Enforces SQLite FK constraints so ON DELETE CASCADE behaves like PostgreSQL
    — the idempotency test (test_amazon_mutation_resync_idempotent_via_delete_facade)
    relies on cascade deletes firing when delete_derived_by_plaid_ids runs.
    """
    db = DB(f"sqlite:///{tmp_path / 'test.db'}", enforce_sqlite_fks=True)
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str = "plaid-amz-001",
    amount_cents: int = 6000,
    posted_at: date = date(2026, 2, 10),
    merchant_descriptor: str = "Amazon",
) -> int:
    """Insert a minimal Amazon-like PlaidTransaction; return its PK."""
    with db.session() as session:
        plaid_txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id="acct-abc",
            item_id=None,
            posted_at=posted_at,
            amount_cents=amount_cents,
            currency="USD",
            merchant_descriptor=merchant_descriptor,
        )
        session.add(plaid_txn)
        session.flush()
        plaid_id: int = plaid_txn.plaid_transaction_id
    return plaid_id


def _seed_amazon_order(
    db: DB,
    plaid_txn_amount_cents: int,
) -> str:
    """Seed an Amazon order with 3 items; return order_id."""
    order_id = "113-1111111-1111111"
    profile = db.create_amazon_login_profile(
        profile_key="primary", display_name="Primary"
    )
    db.upsert_amazon_order(
        order_id=order_id,
        order_date=date(2026, 2, 8),
        order_total_cents=plaid_txn_amount_cents,
        tax_cents=0,
        shipping_cents=0,
        profile_id=profile.profile_id,
    )
    db.upsert_amazon_item(
        order_id=order_id,
        asin="B001",
        description="Wireless Mouse",
        price_cents=2000,
        quantity=1,
    )
    db.upsert_amazon_item(
        order_id=order_id,
        asin="B002",
        description="USB Hub",
        price_cents=2500,
        quantity=1,
    )
    db.upsert_amazon_item(
        order_id=order_id,
        asin="B003",
        description="HDMI Cable",
        price_cents=1500,
        quantity=1,
    )
    return order_id


def _run_mutation(db: DB, plaid_id: int) -> list[int]:
    """Initialize and run the Amazon mutation plugin; return new derived IDs."""
    plugin = AmazonMutationPlugin(db, AmazonMutationPluginConfig())
    plaid_txns = db.get_plaid_transactions_by_ids([plaid_id])
    plaid_txn = plaid_txns[plaid_id]

    plugin.initialize(list(plaid_txns.values()))

    old_derived = db.get_derived_by_plaid_ids([plaid_id]).get(plaid_id, [])
    result = plugin.process(plaid_txn, old_derived)
    return db.bulk_insert_derived_transactions(result.derived_data_list)


def _count_items(db: DB, transaction_id: int) -> int:
    """Count TransactionItem rows for a given transaction_id."""
    with db.session() as session:
        return (
            session.query(TransactionItem)
            .filter_by(transaction_id=transaction_id)
            .count()
        )


def _fetch_items(db: DB, transaction_id: int) -> list[TransactionItem]:
    """Fetch all TransactionItem rows for a given transaction_id."""
    with db.session() as session:
        items = (
            session.query(TransactionItem)
            .filter_by(transaction_id=transaction_id)
            .all()
        )
        for item in items:
            session.expunge(item)
        return items


def _fetch_derived_rows(db: DB, plaid_id: int) -> list[DerivedTransaction]:
    """Fetch all DerivedTransaction rows for a given plaid_transaction_id."""
    with db.session() as session:
        rows = (
            session.query(DerivedTransaction)
            .filter_by(plaid_transaction_id=plaid_id)
            .order_by(DerivedTransaction.split_index)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _as_item_dict(item: TransactionItem) -> dict[str, object]:
    """Extract the fields we care about from a TransactionItem."""
    return {
        "itemization_source": item.itemization_source,
        "source_ref": item.source_ref,
    }


def test_amazon_mutation_writes_transaction_items(tmp_path: Path) -> None:
    """AmazonMutationPlugin writes one TransactionItem per amazon_item."""
    # input
    db = _create_db(tmp_path)
    total_cents = 6000
    plaid_id = _insert_plaid_txn(db, amount_cents=total_cents)
    order_id = _seed_amazon_order(db, total_cents)

    # act
    derived_ids = _run_mutation(db, plaid_id)
    all_items = [item for did in derived_ids for item in _fetch_items(db, did)]

    # expected
    expected_output = {
        "derived_count": 3,
        "items_per_derived": [1, 1, 1],
        "total_item_cents": total_cents,
        "item_sources": [
            {"itemization_source": "amazon_scrape", "source_ref": order_id}
        ]
        * 3,
    }

    # assert
    assert {
        "derived_count": len(derived_ids),
        "items_per_derived": [_count_items(db, did) for did in derived_ids],
        "total_item_cents": sum(item.amount_cents for item in all_items),
        "item_sources": [_as_item_dict(item) for item in all_items],
    } == expected_output


def test_amazon_mutation_resync_idempotent(tmp_path: Path) -> None:
    """Re-running mutation produces no duplicate transaction_items rows.

    Simulates re-sync by deleting old derived rows via ORM (which respects
    the SQLAlchemy cascade="all, delete-orphan" relationship), then re-running
    the mutation.  In production PostgreSQL, the equivalent guarantee is
    provided by the ON DELETE CASCADE constraint on transaction_items.
    """
    # input
    db = _create_db(tmp_path)
    total_cents = 6000
    plaid_id = _insert_plaid_txn(db, amount_cents=total_cents)
    _seed_amazon_order(db, total_cents)

    # act: run mutation once
    first_ids = _run_mutation(db, plaid_id)
    assert len(first_ids) == 3
    # Verify items from first run
    first_item_total = sum(_count_items(db, tid) for tid in first_ids)
    assert first_item_total == 3

    # Delete old derived rows via ORM (respects cascade, matching production behavior)
    with db.session() as session:
        rows = (
            session.query(DerivedTransaction)
            .filter(DerivedTransaction.plaid_transaction_id == plaid_id)
            .all()
        )
        for row in rows:
            session.delete(row)

    # act: run mutation a second time
    second_ids = _run_mutation(db, plaid_id)

    # expected: still 3 derived rows, still 1 item each — no duplicates
    expected_derived_count = 3

    # assert
    assert len(second_ids) == expected_derived_count
    total_item_count = sum(_count_items(db, tid) for tid in second_ids)
    assert total_item_count == expected_derived_count


def test_amazon_mutation_split_group_id_and_index(tmp_path: Path) -> None:
    """Derived rows from one Amazon split share split_group_id; indexes are 0..N-1."""
    # input
    db = _create_db(tmp_path)
    total_cents = 6000
    plaid_id = _insert_plaid_txn(db, amount_cents=total_cents)
    _seed_amazon_order(db, total_cents)

    # act
    derived_ids = _run_mutation(db, plaid_id)
    derived_rows = _fetch_derived_rows(db, plaid_id)

    # expected: 3 rows, all with the same non-None split_group_id, split_index 0..2
    expected_output = {
        "count": 3,
        "split_group_ids_unique": 1,
        "split_group_id_is_set": True,
        "split_indexes": [0, 1, 2],
    }

    group_ids = {row.split_group_id for row in derived_rows}
    all_set = all(row.split_group_id is not None for row in derived_rows)
    indexes = sorted(
        row.split_index for row in derived_rows if row.split_index is not None
    )

    # assert
    assert {
        "count": len(derived_ids),
        "split_group_ids_unique": len(group_ids),
        "split_group_id_is_set": all_set,
        "split_indexes": indexes,
    } == expected_output


def test_amazon_mutation_resync_idempotent_via_delete_facade(tmp_path: Path) -> None:
    """Re-running mutation via delete_derived_by_plaid_ids produces no duplicate items.

    This exercises the production delete path (bulk SQL DELETE with ON DELETE CASCADE)
    rather than the ORM cascade path tested by test_amazon_mutation_resync_idempotent.
    """
    # input
    db = _create_db(tmp_path)
    total_cents = 6000
    plaid_id = _insert_plaid_txn(db, amount_cents=total_cents)
    _seed_amazon_order(db, total_cents)

    # act: run mutation once
    first_ids = _run_mutation(db, plaid_id)
    assert len(first_ids) == 3
    first_item_total = sum(_count_items(db, tid) for tid in first_ids)
    assert first_item_total == 3

    # Delete via the public facade method (production code path)
    deleted = db.delete_derived_by_plaid_ids([plaid_id])
    assert deleted == 3

    # act: run mutation a second time
    second_ids = _run_mutation(db, plaid_id)

    # expected: 3 derived rows, 1 item each — no duplicates
    expected_output = {
        "derived_count": 3,
        "total_item_count": 3,
    }

    # assert
    assert {
        "derived_count": len(second_ids),
        "total_item_count": sum(_count_items(db, tid) for tid in second_ids),
    } == expected_output
