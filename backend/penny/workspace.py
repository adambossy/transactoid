"""Workspace directory resolution.

The workspace directory holds user-specific runtime data such as the
``memory/`` and ``reports/`` subdirectories. The default location is
``~/.transactoid`` — preserved from the prior product name so existing user
state (budget, merchant rules, prior reports) is picked up without
migration. Override with the ``PENNY_WORKSPACE`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

PENNY_WORKSPACE = "PENNY_WORKSPACE"

_DEFAULT_WORKSPACE = Path.home() / ".transactoid"


def resolve_workspace_dir() -> Path:
    """Return the workspace root directory.

    Uses ``$PENNY_WORKSPACE`` when set, otherwise ``~/.transactoid``.
    """
    env_value = os.environ.get(PENNY_WORKSPACE, "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return _DEFAULT_WORKSPACE


def resolve_memory_dir() -> Path:
    """Return the ``memory/`` subdirectory inside the workspace."""
    return resolve_workspace_dir() / "memory"


def resolve_reports_dir() -> Path:
    """Return the ``reports/`` subdirectory inside the workspace."""
    return resolve_workspace_dir() / "reports"
