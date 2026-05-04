"""Smoke tests for EmailReceipt ORM model: dedup constraint."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import EmailReceipt


def _create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _insert_receipt(db: DB, message_id: str) -> int:
    """Insert an EmailReceipt with the given message_id; return its PK."""
    with db.session() as session:
        receipt = EmailReceipt(
            message_id=message_id,
            subject="Your Amazon.com order has shipped",
            sender="shipment-tracking@amazon.com",
        )
        session.add(receipt)
        session.flush()
        receipt_id: int = receipt.receipt_id
        session.expunge(receipt)
    return receipt_id


def test_email_receipt_duplicate_message_id_raises(tmp_path: Path) -> None:
    # input
    message_id = "msg-abc-001"
    db = _create_db(tmp_path)

    # setup: insert first receipt successfully
    _insert_receipt(db, message_id)

    # act + assert: inserting a duplicate message_id raises IntegrityError
    with pytest.raises(IntegrityError):
        _insert_receipt(db, message_id)
