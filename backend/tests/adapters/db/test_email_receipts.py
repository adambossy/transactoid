"""Smoke tests for EmailReceipt ORM model: dedup constraint."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from penny.adapters.db.models import EmailReceipt
from penny.db import get_db


def _insert_receipt(message_id: str) -> int:
    """Insert an EmailReceipt with the given message_id; return its PK."""
    with get_db().session() as session:
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


def test_email_receipt_duplicate_message_id_raises(
    isolated_db: pytest.FixtureRequest,
) -> None:
    # input
    message_id = "msg-abc-001"
    get_db().create_schema()

    # setup: insert first receipt successfully
    _insert_receipt(message_id)

    # act + assert: inserting a duplicate message_id raises IntegrityError
    with pytest.raises(IntegrityError):
        _insert_receipt(message_id)
