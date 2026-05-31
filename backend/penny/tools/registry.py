"""Build the phase-1 toolset.

Phase 1 ships three tools — ``list_plaid_accounts`` (Plaid surface),
``run_sql`` (analytics), and ``bash`` (sandboxed shell). Phase 2 adds the
Plaid pipeline; phase 3 adds skills, memory tools, and the remaining
domain tools.
"""

from __future__ import annotations

from agent_harness import StaticToolset
from agent_harness.core.toolsets import Toolset

from .analytics import run_sql
from .bash import bash
from .plaid import list_plaid_accounts


def build_toolset() -> Toolset:
    return StaticToolset(
        name="penny",
        tools=[list_plaid_accounts, run_sql, bash],
    )
