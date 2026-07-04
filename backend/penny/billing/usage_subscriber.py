"""Subscribe harness ``ModelUsage`` events to the subsidy ledger.

An ``EventBus`` subscriber (peer to the OTEL/trace subscriber): for the duration
of one run it drains the bus and, on each ``ModelUsage`` event, appends a
``UsageEvent`` for the run's ``RequestContext``. Attached only for a **subsidized**
run — the gate does not wire it for a BYO decision, so a user's own key spend
never touches the subsidy ledger.

Usage mirrors ``observability.start_run_trace_task``: subscribe BEFORE the run
publishes, then ``await`` the returned task after the bus closes so no event is
dropped.
"""

from __future__ import annotations

import asyncio

from agent_harness.core.events import EventBus, ModelUsage

from penny.tenancy.context import RequestContext

from . import metering
from .session import BillingSession


def start_usage_subscriber_task(
    bus: EventBus | None,
    ctx: RequestContext,
    *,
    billing: BillingSession | None = None,
) -> asyncio.Task[None] | None:
    """Attach a ledger-writing subscriber to ``bus``; return its task (or None).

    Each ``ModelUsage`` is recorded in its own short web transaction so a slow
    write can't stall the stream (the DB call runs in a worker thread).
    """
    if bus is None:
        return None
    session = billing or BillingSession()
    subscription = bus.subscribe()

    def _record(event: ModelUsage) -> None:
        with session.begin(ctx) as s:
            metering.record_usage(s, ctx, event)

    async def _run() -> None:
        async for event in subscription:
            if isinstance(event, ModelUsage):
                await asyncio.to_thread(_record, event)

    return asyncio.create_task(_run())
