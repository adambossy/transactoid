"""Minimal standalone ``byo_credential`` reminder (phase-5-reuse placeholder).

Phase 5's reminder subsystem + generative-UI card is not built yet, so this is a
deliberately small stand-in: an **idempotent per-user** record that a
credential-connect nudge is pending. The gate's Blocked path enqueues it; a
future phase-5 producer will replace this in-memory record with the real
system-reminder + inline card (see phase-2b-decisions D8).

Process-local and non-durable on purpose — it exists to carry intent + the
idempotency contract ("exactly one per user"), not to persist across restarts.
"""

from __future__ import annotations

import uuid

_KIND = "byo_credential"

# Users with a pending byo_credential nudge (process-local placeholder store).
_PENDING: set[uuid.UUID] = set()


def enqueue_byo_credential(user_id: uuid.UUID) -> bool:
    """Record a pending connect nudge for ``user_id``. Idempotent.

    Returns ``True`` if newly enqueued, ``False`` if one was already pending —
    so a repeatedly-blocked user accrues exactly one reminder.
    """
    if user_id in _PENDING:
        return False
    _PENDING.add(user_id)
    return True


def has_pending(user_id: uuid.UUID) -> bool:
    """Whether a byo_credential nudge is pending for ``user_id``."""
    return user_id in _PENDING


def clear(user_id: uuid.UUID) -> None:
    """Drop the pending nudge (e.g. after the user connects a provider)."""
    _PENDING.discard(user_id)


def kind() -> str:
    """The reminder kind string this module produces."""
    return _KIND
