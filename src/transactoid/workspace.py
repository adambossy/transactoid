"""Workspace directory resolution.

The workspace directory (default ``~/.transactoid``) holds user-specific
runtime data such as the ``memory/`` subdirectory. Override the default
location by setting the ``TRANSACTOID_WORKSPACE`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

TRANSACTOID_WORKSPACE = "TRANSACTOID_WORKSPACE"

_DEFAULT_WORKSPACE = Path.home() / ".transactoid"


def resolve_workspace_dir() -> Path:
    """Return the workspace root directory.

    Uses ``$TRANSACTOID_WORKSPACE`` when set, otherwise ``~/.transactoid``.
    """
    env_value = os.environ.get(TRANSACTOID_WORKSPACE, "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return _DEFAULT_WORKSPACE


def resolve_memory_dir() -> Path:
    """Return the ``memory/`` subdirectory inside the workspace."""
    return resolve_workspace_dir() / "memory"


def resolve_reports_dir() -> Path:
    """Return the ``reports/`` subdirectory inside the workspace."""
    return resolve_workspace_dir() / "reports"
