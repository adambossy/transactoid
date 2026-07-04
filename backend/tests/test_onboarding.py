"""Deterministic onboarding trigger engine (``penny.onboarding``).

Onboarding items are website/app state in the ``web`` schema (decision D1), so
``ensure_items`` / ``evaluate`` take a web session (``owner_web_session``) rather
than the finance session the stale plan body used. ``_ctx`` creates both schemas
and seeds a finance identity so downstream Plaid tests (which reuse it) can write
finance rows.
"""

from __future__ import annotations

import uuid

from penny.api.persistence.engine import create_web_schema
from penny.api.persistence.models import OnboardingItem
from penny.api.persistence.tenant import owner_web_session
from penny.db import get_db
from penny.onboarding import TurnSignals, ensure_items, evaluate
from penny.tenancy.context import RequestContext


def _ctx() -> RequestContext:
    from penny.adapters.db.models import Household, User

    db = get_db()
    db.create_schema()
    create_web_schema()
    hh = uuid.uuid4()
    u = uuid.uuid4()
    with db.session() as s:
        s.add(Household(household_id=hh, name="H"))
        s.flush()
        s.add(User(user_id=u, household_id=hh, email="a@x.com"))
        s.flush()
    return RequestContext(user_id=u, household_id=hh)


def _signals(**kw) -> TurnSignals:
    base = {
        "has_linked_items": False,
        "household_member_count": 1,
        "response_had_categorized_rows": False,
        "user_corrected_category": False,
    }
    base.update(kw)
    return TurnSignals(**base)


def test_connect_plaid_fires_every_turn_until_resolved(isolated_db):
    ctx = _ctx()
    with owner_web_session(ctx) as s:
        ensure_items(s, ctx)
        first = evaluate(s, ctx, _signals())
        second = evaluate(s, ctx, _signals())
    assert first and "connect_plaid" in first
    assert second and "connect_plaid" in second  # every turn, deterministic
    with owner_web_session(ctx) as s:  # dismiss -> silence
        s.query(OnboardingItem).filter_by(item_key="connect_plaid").update(
            {"status": "dismissed"}
        )
        assert evaluate(s, ctx, _signals()) is None


def test_custom_taxonomy_fires_after_three_categorized_turns(isolated_db):
    ctx = _ctx()
    with owner_web_session(ctx) as s:
        ensure_items(s, ctx)
        s.query(OnboardingItem).filter_by(item_key="connect_plaid").update(
            {"status": "accepted"}
        )
        sig = _signals(has_linked_items=True, response_had_categorized_rows=True)
        assert evaluate(s, ctx, sig) is None  # turn 1
        assert evaluate(s, ctx, sig) is None  # turn 2
        third = evaluate(s, ctx, sig)  # turn 3 -> fires
    assert third and "custom_taxonomy" in third


def test_same_state_same_output(isolated_db):
    ctx = _ctx()
    with owner_web_session(ctx) as s:
        ensure_items(s, ctx)
        a = evaluate(s, ctx, _signals())
    with owner_web_session(ctx) as s:
        b = evaluate(s, ctx, _signals())
    # deterministic template: the text before the first item key is identical
    assert a.split("connect_plaid")[0] == b.split("connect_plaid")[0]
