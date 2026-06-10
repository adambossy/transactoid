"""Build Penny's core toolset (all non-plugin domain tools)."""

from __future__ import annotations

from agent_harness import StaticToolset
from agent_harness.core.toolsets import Toolset

from .analytics import generate_chart, run_sql
from .bash import bash
from .delivery import send_email_report, upload_artifact_to_r2
from .memory import generate_memory_index
from .plaid import connect_new_account, list_plaid_accounts
from .recategorize import recategorize_merchant, tag_transactions
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
            tag_transactions,
            migrate_taxonomy,
            split_transaction,
            record_refund,
            # Analytics
            run_sql,
            generate_chart,
            # Delivery
            upload_artifact_to_r2,
            send_email_report,
            # Memory
            generate_memory_index,
            # Sandbox
            bash,
        ],
    )
