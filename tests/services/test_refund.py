"""Tests for record_refund service."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from transactoid.adapters.db.facade import DB
from transactoid.adapters.db.models import DerivedTransaction, PlaidTransaction
from transactoid.errors import RefundError
from transactoid.services.refund import record_refund

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_db(tmp_path: Path) -> DB:
    """Create a file-backed SQLite DB with full schema."""
    db = DB(f"sqlite:///{tmp_path / 'test_refund.db'}")
    db.create_schema()
    return db


def _insert_plaid_txn(
    db: DB,
    *,
    external_id: str,
    amount_cents: int = 5000,
    posted_at: date = date(2026, 1, 10),
    account_id: str = "acct-abc",
    currency: str = "USD",
) -> int:
    """Insert a minimal PlaidTransaction; return its PK."""
    with db.session() as session:
        txn = PlaidTransaction(
            external_id=external_id,
            source="PLAID",
            account_id=account_id,
            item_id=None,
            posted_at=posted_at,
            amount_cents=amount_cents,
            currency=currency,
            merchant_descriptor="Test Merchant",
        )
        session.add(txn)
        session.flush()
        plaid_id: int = txn.plaid_transaction_id
    return plaid_id


def _insert_derived_txn(
    db: DB,
    plaid_transaction_id: int,
    *,
    external_id: str,
    amount_cents: int = 5000,
    posted_at: date = date(2026, 1, 10),
    is_verified: bool = False,
) -> int:
    """Insert a DerivedTransaction; return its PK."""
    with db.session() as session:
        txn = DerivedTransaction(
            plaid_transaction_id=plaid_transaction_id,
            external_id=external_id,
            amount_cents=amount_cents,
            posted_at=posted_at,
            is_verified=is_verified,
        )
        session.add(txn)
        session.flush()
        txn_id: int = txn.transaction_id
    return txn_id


def _fetch_derived(db: DB, txn_id: int) -> DerivedTransaction | None:
    """Return the DerivedTransaction row or None."""
    with db.session() as session:
        row = session.get(DerivedTransaction, txn_id)
        if row is not None:
            session.expunge(row)
        return row


def _as_refund_dict(row: DerivedTransaction) -> dict[str, object]:
    """Extract refund-relevant fields for equality checks."""
    return {
        "refund_of_transaction_id": row.refund_of_transaction_id,
        "refund_matched_by": row.refund_matched_by,
        "refund_matched_at_is_set": row.refund_matched_at is not None,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_record_refund_happy_path(tmp_path: Path) -> None:
    # input
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(db, external_id="orig-plaid", amount_cents=5000)
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived", amount_cents=5000
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived",
        amount_cents=-1000,
        posted_at=date(2026, 1, 15),
    )

    # act
    record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_id)

    # expected
    row = _fetch_derived(db, refund_id)
    assert row is not None
    expected = {
        "refund_of_transaction_id": orig_id,
        "refund_matched_by": "user",
        "refund_matched_at_is_set": True,
    }

    # assert
    assert _as_refund_dict(row) == expected


# ---------------------------------------------------------------------------
# Not-found errors
# ---------------------------------------------------------------------------


def test_record_refund_unknown_refund_id(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, external_id="orig-plaid-2")
    orig_id = _insert_derived_txn(db, plaid_id, external_id="orig-derived-2")

    with pytest.raises(RefundError, match="transaction 9999 not found"):
        record_refund(db, refund_txn_id=9999, original_txn_id=orig_id)


def test_record_refund_unknown_original_id(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(
        db, external_id="refund-plaid-3", amount_cents=-500, posted_at=date(2026, 2, 1)
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_id,
        external_id="refund-derived-3",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )

    with pytest.raises(RefundError, match="transaction 9999 not found"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=9999)


# ---------------------------------------------------------------------------
# Self-link rejection
# ---------------------------------------------------------------------------


def test_record_refund_self_link_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_id = _insert_plaid_txn(db, external_id="self-plaid")
    txn_id = _insert_derived_txn(db, plaid_id, external_id="self-derived")

    with pytest.raises(RefundError, match="cannot be linked to itself"):
        record_refund(db, refund_txn_id=txn_id, original_txn_id=txn_id)


# ---------------------------------------------------------------------------
# Verified-row rejections
# ---------------------------------------------------------------------------


def test_record_refund_verified_refund_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(db, external_id="orig-plaid-4")
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-4",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )
    orig_id = _insert_derived_txn(db, plaid_orig, external_id="orig-derived-4")
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-4",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
        is_verified=True,
    )

    with pytest.raises(RefundError, match="is verified and cannot be modified"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_id)


def test_record_refund_verified_original_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(db, external_id="orig-plaid-5")
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-5",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-5", is_verified=True
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-5",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )

    with pytest.raises(RefundError, match="is verified and cannot be modified"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_id)


# ---------------------------------------------------------------------------
# Already-linked rejection
# ---------------------------------------------------------------------------


def test_record_refund_already_linked_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig_a = _insert_plaid_txn(db, external_id="orig-plaid-6a")
    plaid_orig_b = _insert_plaid_txn(db, external_id="orig-plaid-6b")
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-6",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )
    orig_a_id = _insert_derived_txn(db, plaid_orig_a, external_id="orig-derived-6a")
    orig_b_id = _insert_derived_txn(db, plaid_orig_b, external_id="orig-derived-6b")
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-6",
        amount_cents=-500,
        posted_at=date(2026, 2, 1),
    )

    # Link to orig_a first
    record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_a_id)

    # Attempt to link to a *different* original
    with pytest.raises(RefundError, match="already linked"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_b_id)


# ---------------------------------------------------------------------------
# Pre-date rejection
# ---------------------------------------------------------------------------


def test_record_refund_predates_original_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(
        db, external_id="orig-plaid-7", posted_at=date(2026, 3, 15)
    )
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-7",
        amount_cents=-500,
        # 30 days before the original — well outside the 1-day grace window
        posted_at=date(2026, 2, 13),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-7", posted_at=date(2026, 3, 15)
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-7",
        amount_cents=-500,
        posted_at=date(2026, 2, 13),
    )

    with pytest.raises(RefundError, match="predates"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_id)


# ---------------------------------------------------------------------------
# Currency mismatch rejection
# ---------------------------------------------------------------------------


def test_record_refund_currency_mismatch_rejected(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(
        db, external_id="orig-plaid-8", currency="USD", posted_at=date(2026, 1, 10)
    )
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-8",
        amount_cents=-500,
        currency="EUR",
        posted_at=date(2026, 1, 15),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-8", posted_at=date(2026, 1, 10)
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-8",
        amount_cents=-500,
        posted_at=date(2026, 1, 15),
    )

    with pytest.raises(RefundError, match="currency mismatch"):
        record_refund(db, refund_txn_id=refund_id, original_txn_id=orig_id)


# ---------------------------------------------------------------------------
# Account mismatch warning (success)
# ---------------------------------------------------------------------------


def test_record_refund_account_mismatch_warns(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(
        db,
        external_id="orig-plaid-9",
        account_id="acct-one",
        posted_at=date(2026, 1, 10),
    )
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-9",
        amount_cents=-500,
        account_id="acct-two",
        posted_at=date(2026, 1, 15),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-9", posted_at=date(2026, 1, 10)
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-9",
        amount_cents=-500,
        posted_at=date(2026, 1, 15),
    )

    mock_logger = MagicMock()
    mock_logger.bind.return_value = mock_logger

    # act — must succeed despite account mismatch
    record_refund(
        db,
        refund_txn_id=refund_id,
        original_txn_id=orig_id,
        _logger=mock_logger,
    )

    # expected: link was created
    row = _fetch_derived(db, refund_id)
    assert row is not None
    assert row.refund_of_transaction_id == orig_id

    # warning was emitted
    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Positive-amount warning (success)
# ---------------------------------------------------------------------------


def test_record_refund_positive_amount_warns(tmp_path: Path) -> None:
    db = create_db(tmp_path)
    plaid_orig = _insert_plaid_txn(
        db, external_id="orig-plaid-10", posted_at=date(2026, 1, 10)
    )
    plaid_refund = _insert_plaid_txn(
        db,
        external_id="refund-plaid-10",
        # Positive amount is unusual for a refund but not rejected
        amount_cents=500,
        posted_at=date(2026, 1, 15),
    )
    orig_id = _insert_derived_txn(
        db, plaid_orig, external_id="orig-derived-10", posted_at=date(2026, 1, 10)
    )
    refund_id = _insert_derived_txn(
        db,
        plaid_refund,
        external_id="refund-derived-10",
        amount_cents=500,
        posted_at=date(2026, 1, 15),
    )

    mock_logger = MagicMock()
    mock_logger.bind.return_value = mock_logger

    # act — must succeed
    record_refund(
        db,
        refund_txn_id=refund_id,
        original_txn_id=orig_id,
        _logger=mock_logger,
    )

    # expected: link was created
    row = _fetch_derived(db, refund_id)
    assert row is not None
    assert row.refund_of_transaction_id == orig_id

    # warning was emitted about positive amount
    mock_logger.warning.assert_called_once()
