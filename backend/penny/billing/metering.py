"""Usage ledger + per-user subsidy record — the metering half of the gate.

``record_usage`` appends one ``UsageEvent`` per subsidized model completion
(from the harness ``ModelUsage`` event); ``remaining_cents`` derives the runway
as ``subsidy_granted - sum(cost_cents)``; ``grant_subsidy`` creates the per-user
grant once (idempotent — the first Plaid link grants, later ones no-op).

Every function takes an already-owner-bound web ``Session`` (see
``penny.billing.session.BillingSession``) and the ``RequestContext``, and filters
by the real ``user_id`` (the SQLite tenant layer; Postgres also enforces RLS).
"""

from __future__ import annotations

from datetime import datetime

from agent_harness.core.events import ModelUsage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from penny.tenancy.context import RequestContext

from .models import UsageEvent, UserBilling


def _cost_cents(usage: ModelUsage) -> int:
    """Whole-cent cost for one completion (prices are USD; Cost.total is $)."""
    return round(usage.cost.total * 100)


def record_usage(session: Session, ctx: RequestContext, usage: ModelUsage) -> None:
    """Append one ledger row for a subsidized completion.

    Only subsidized runs are recorded — a BYO run never reaches here (the gate
    does not attach the usage subscriber for a BYO decision).
    """
    u = usage.usage
    session.add(
        UsageEvent(
            user_id=ctx.user_id,
            model=usage.model_name,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_tokens=u.cache_read_tokens + u.cache_write_tokens,
            cost_cents=_cost_cents(usage),
        )
    )


def spend_cents(session: Session, ctx: RequestContext) -> int:
    """Total subsidized spend so far — ``sum(cost_cents)`` for this user."""
    stmt = select(func.coalesce(func.sum(UsageEvent.cost_cents), 0)).where(
        UsageEvent.user_id == ctx.user_id
    )
    return int(session.execute(stmt).scalar_one())


def granted_cents(session: Session, ctx: RequestContext) -> int:
    """The user's cumulative subsidy grant (0 if never granted)."""
    row = session.get(UserBilling, ctx.user_id)
    return row.subsidy_granted_cents if row is not None else 0


def remaining_cents(session: Session, ctx: RequestContext) -> int:
    """Runway left = granted - spend. Can be negative only transiently (a final
    completion can overshoot the last gate check); the gate treats ``<= 0`` as
    exhausted."""
    return granted_cents(session, ctx) - spend_cents(session, ctx)


def grant_subsidy(session: Session, ctx: RequestContext, *, cents: int) -> bool:
    """Grant the per-user subsidy once. Returns ``True`` if newly granted.

    Idempotent: if the user already has a billing row, this is a no-op (a second
    Plaid link for the same user does not re-grant). A row is created under the
    caller's transaction; the ``(user_id)`` PK + the owner RLS keep it private.
    """
    row = session.get(UserBilling, ctx.user_id)
    if row is not None:
        return False
    session.add(UserBilling(user_id=ctx.user_id, subsidy_granted_cents=cents))
    return True


def touch_billing(session: Session, ctx: RequestContext) -> None:
    """Bump the billing row's ``updated_at`` (used after accrual)."""
    row = session.get(UserBilling, ctx.user_id)
    if row is not None:
        row.updated_at = datetime.now()
