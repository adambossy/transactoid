"""Split service: replace a single derived transaction with N user-defined parts.

Public API
----------
    split_transaction(db, txn_id, parts) -> list[int]

All validation and the DB write happen atomically in one session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from transactoid.adapters.db.models import DerivedTransaction
from transactoid.errors import SplitError

if TYPE_CHECKING:
    from transactoid.adapters.db.facade import DB


def split_transaction(db: DB, txn_id: int, parts: list[int]) -> list[int]:
    """Replace one derived transaction with N new rows sharing a split_group_id.

    Validations (in order):
    - ``txn_id`` must exist.
    - The row must not be ``is_verified=True``.
    - The underlying ``plaid_transaction`` must not match any ``amazon_orders``
      row — Amazon-split rows are managed automatically; manual split is rejected.
    - ``len(parts) >= 2``.
    - ``sum(parts) == original.amount_cents`` (exact).
    - Every element of ``parts`` must be > 0.

    The entire operation (delete + insert N rows) runs inside a single session
    and is rolled back atomically if any step fails.

    Args:
        db: Database facade.
        txn_id: Primary key of the derived_transaction to split.
        parts: List of cent amounts; must sum to original amount_cents.

    Returns:
        List of new transaction_ids in split_index order (0 … N-1).

    Raises:
        SplitError: On any validation failure or write error.
    """
    with db.session() as session:
        derived = session.get(DerivedTransaction, txn_id)

        if derived is None:
            raise SplitError(f"transaction {txn_id} not found")

        if derived.is_verified:
            raise SplitError(
                f"transaction {txn_id} is verified and cannot be modified; "
                "un-verify first"
            )

        # Amazon gating: reject if the underlying plaid txn matches any amazon order.
        matched_order = db.get_amazon_order_for_plaid_txn(
            session, derived.plaid_transaction_id
        )
        if matched_order is not None:
            raise SplitError(
                f"transaction {txn_id} is part of Amazon order "
                f"#{matched_order.order_id}; Amazon transactions and their items "
                "are split automatically from order data and cannot be split manually"
            )

        if len(parts) < 2:
            raise SplitError(f"split requires at least 2 parts; got {len(parts)}")

        parts_total = sum(parts)
        original_amount = derived.amount_cents
        if parts_total != original_amount:
            raise SplitError(
                f"split amounts {parts_total / 100:.2f} != "
                f"original {original_amount / 100:.2f}; they must sum exactly"
            )

        for idx, part in enumerate(parts):
            if part <= 0:
                raise SplitError(f"all parts must be > 0; part[{idx}] = {part}")

        # Snapshot fields we need before deleting the original row.
        plaid_transaction_id = derived.plaid_transaction_id
        posted_at = derived.posted_at
        merchant_descriptor = derived.merchant_descriptor
        merchant_id = derived.merchant_id
        category_id = derived.category_id
        category_model = derived.category_model
        category_method = derived.category_method
        category_assigned_at = derived.category_assigned_at
        web_search_summary = derived.web_search_summary
        original_external_id = derived.external_id

        # Delete the original row first, within this session.
        session.delete(derived)
        session.flush()

        split_group_id = str(uuid.uuid4())
        new_ids: list[int] = []

        for split_index, part_cents in enumerate(parts):
            new_external_id = f"{original_external_id}:split:{split_index}"
            new_row = DerivedTransaction(
                plaid_transaction_id=plaid_transaction_id,
                external_id=new_external_id,
                amount_cents=part_cents,
                posted_at=posted_at,
                merchant_descriptor=merchant_descriptor,
                merchant_id=merchant_id,
                category_id=category_id,
                category_model=category_model,
                category_method=category_method,
                category_assigned_at=category_assigned_at,
                web_search_summary=web_search_summary,
                is_verified=False,
                split_group_id=split_group_id,
                split_source="user_split",
                split_index=split_index,
            )
            session.add(new_row)
            session.flush()
            new_ids.append(new_row.transaction_id)

        return new_ids
