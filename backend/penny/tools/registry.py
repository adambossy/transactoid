"""Build Penny's core toolset (all non-plugin domain tools)."""

from __future__ import annotations

from agent_harness import StaticToolset
from agent_harness.core.toolsets import Toolset

from .analytics import generate_chart, run_sql
from .audit import (
    category_history,
    find_similar_tagged_transactions,
    transaction_tags,
)
from .bash import bash
from .delivery import send_email_report, upload_artifact_to_r2
from .memory import generate_memory_index
from .plaid import connect_new_account, list_plaid_accounts
from .recategorize import (
    recategorize_merchant,
    recategorize_transaction,
    tag_transactions,
)
from .sign_conventions import (
    list_sign_conventions,
    re_derive_account,
    set_sign_convention,
)
from .sync import sync_transactions
from .taxonomy import migrate_taxonomy
from .transactions import record_refund, split_transaction


def build_toolset() -> Toolset:
    return StaticToolset(
        name="penny",
        tools=[
            # Plaid + sync
            list_plaid_accounts,
            connect_new_account,
            sync_transactions,
            # Mutations
            recategorize_merchant,
            recategorize_transaction,
            tag_transactions,
            migrate_taxonomy,
            split_transaction,
            record_refund,
            # Sign conventions + re-derive
            set_sign_convention,
            list_sign_conventions,
            re_derive_account,
            # Analytics
            run_sql,
            generate_chart,
            # Audit / history (read-only)
            category_history,
            transaction_tags,
            find_similar_tagged_transactions,
            # Delivery
            upload_artifact_to_r2,
            send_email_report,
            # Memory
            generate_memory_index,
            # Sandbox
            bash,
        ],
    )
