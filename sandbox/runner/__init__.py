"""The agent-runtime shell that runs inside the Modal sandbox.

Imports agent-harness and the shared ``protocol`` package only — never
``penny``. Everything conversation-specific arrives in the ``TurnPayload``.
"""

from __future__ import annotations

from .server import create_app

__all__ = ["create_app"]
