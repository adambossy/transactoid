"""Per-conversation sandbox record + its state machine's backing store.

The conversation record is the durable thing (Vercel's two-level identity): it
holds the sandbox generation's id/tunnel, the one snapshot image, the reap
lease (``reap_epoch``), and the idle clock. The Modal sandbox itself is the
disposable session. On the single-user main baseline this store is in-memory;
the account-creation branch swaps in a website-owned SQL store behind the same
interface.

The per-conversation ``asyncio.Lock`` stands in for the DB row lock that makes
the dispatch/reaper race safe across a Fly fleet.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import enum


class SandboxState(enum.Enum):
    IDLE = "idle"  # sandbox live, no turn running, idle clock ticking
    ACTIVE = "active"  # a turn is running
    REAPING = "reaping"  # reaper claimed the box; snapshot in flight
    TERMINATED = "terminated"  # box gone; snapshot is the restore point


@dataclass
class ConversationSandbox:
    conversation_id: str
    state: SandboxState = SandboxState.TERMINATED  # no sandbox yet == cold
    sandbox_id: str | None = None
    tunnel_url: str | None = None
    snapshot_image_id: str | None = None
    reap_epoch: int = 0
    last_activity_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class InMemorySandboxStore:
    """Conversation-id → :class:`ConversationSandbox` (main baseline)."""

    def __init__(self) -> None:
        self._by_id: dict[str, ConversationSandbox] = {}

    def get(self, conversation_id: str) -> ConversationSandbox:
        rec = self._by_id.get(conversation_id)
        if rec is None:
            rec = ConversationSandbox(conversation_id=conversation_id)
            self._by_id[conversation_id] = rec
        return rec
