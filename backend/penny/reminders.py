"""DB-backed reminder queue implementing the harness ``ReminderQueue`` protocol.

Website/app state (decision D1/D5): a ``DbReminderQueue`` persists reminders in
the ``web`` schema keyed by conversation, so an enqueue from one HTTP request
(e.g. the Plaid exchange endpoint) survives until the *next* agent run drains it.
It is injected into the agent (``build_agent(reminders=...)`` → ``Agent``) by the
website; the agent factory never imports it, keeping agent/website segregation
intact.

Override semantics mirror ``InMemoryReminderQueue``: ``override=True`` (default)
upserts on ``(conversation_id, kind)`` so only the latest state of a kind flushes;
``override=False`` appends by suffixing the stored kind (``kind#<hex>``), which
``drain`` strips when rebuilding the ``Reminder``.
"""

from __future__ import annotations

import asyncio
import uuid

from agent_harness.extras.reminders import Reminder

from penny.api.persistence.models import QueuedReminder
from penny.api.persistence.tenant import owner_web_session
from penny.tenancy.context import RequestContext


class DbReminderQueue:
    """A ``ReminderQueue`` backed by ``web.queued_reminders`` for one principal."""

    def __init__(self, ctx: RequestContext) -> None:
        self._ctx = ctx

    async def enqueue(
        self, session_id: str, kind: str, content: str, *, override: bool = True
    ) -> None:
        await asyncio.to_thread(
            self._enqueue_sync, session_id, kind, content, override
        )

    def _enqueue_sync(
        self, session_id: str, kind: str, content: str, override: bool
    ) -> None:
        stored_kind = kind if override else f"{kind}#{uuid.uuid4().hex[:8]}"
        with owner_web_session(self._ctx) as s:
            if override:
                s.query(QueuedReminder).filter_by(
                    conversation_id=session_id,
                    kind=kind,
                    household_id=self._ctx.household_id,
                    owner_user_id=self._ctx.user_id,
                ).delete(synchronize_session=False)
            s.add(
                QueuedReminder(
                    conversation_id=session_id,
                    kind=stored_kind,
                    content=content,
                    household_id=self._ctx.household_id,
                    owner_user_id=self._ctx.user_id,
                )
            )

    async def drain(self, session_id: str) -> list[Reminder]:
        return await asyncio.to_thread(self._drain_sync, session_id)

    def _drain_sync(self, session_id: str) -> list[Reminder]:
        with owner_web_session(self._ctx) as s:
            rows = (
                s.query(QueuedReminder)
                .filter_by(
                    conversation_id=session_id,
                    household_id=self._ctx.household_id,
                    owner_user_id=self._ctx.user_id,
                )
                .order_by(QueuedReminder.id)
                .all()
            )
            out = [
                Reminder(kind=r.kind.split("#", 1)[0], content=r.content) for r in rows
            ]
            for r in rows:
                s.delete(r)
            return out
