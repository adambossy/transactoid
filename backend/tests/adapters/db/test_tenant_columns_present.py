from pathlib import Path

import sqlalchemy as sa

from penny.adapters.db.facade import DB

OWNER_VIS_TABLES = [
    "plaid_transactions",
    "derived_transactions",
    "transaction_items",
    "transaction_tags",
    "email_receipts",
    "pending_receipt_matches",
    "account_sign_conventions",
    "amazon_login_profiles",
    "amazon_orders",
    "amazon_items",
]


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_tenant_columns_exist(tmp_path):
    db = _create_db(tmp_path)
    insp = sa.inspect(db._engine)
    for table in OWNER_VIS_TABLES:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert {"household_id", "owner_user_id", "visibility"} <= cols, table
    plaid_items_cols = {c["name"] for c in insp.get_columns("plaid_items")}
    assert {"household_id", "owner_user_id"} <= plaid_items_cols
    assert "visibility" not in plaid_items_cols


def test_household_only_tables_have_household_id(tmp_path):
    db = _create_db(tmp_path)
    insp = sa.inspect(db._engine)
    for table in ["tags", "transaction_category_events"]:
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "household_id" in cols, table
        assert "owner_user_id" not in cols, table
