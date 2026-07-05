"""The pre-dispatch budget gate + the grant-on-Plaid-link subsidy policy.

Run **before** building the per-request agent, the gate decides how a user's
turn is credentialed:

- ``UseByo`` — the user has a connected BYO credential for the active provider →
  build the model client with it; the user's own provider bills them, so **no**
  subsidy accounting (the usage subscriber is not attached).
- ``UseSubsidy`` — no BYO, but subsidy runway remains → run on the platform key
  and accrue each completion to the ledger afterward.
- ``Blocked`` — no BYO and runway exhausted (or no platform key configured) →
  do **not** run the model; enqueue the connect prompt and return a friendly
  turn.

Fail-closed: with no usable credential the decision is ``Blocked``, never a
silent reach for an ambient env key beyond the remaining subsidy (the plan's
"no ambient/global key for a user run" invariant).

``grant_subsidy_on_plaid_link`` is Penny's subsidy *policy* — kept separate from
the generic gate — and is the website-owned seam a Plaid exchange calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_harness.core.credentials import Credential
from sqlalchemy.orm import Session

from penny.tenancy.context import RequestContext

from . import metering, vault
from .prices import ACTIVE_PROVIDER, subsidy_cents, subsidy_provider_key


@dataclass(frozen=True, slots=True)
class UseDefault:
    """Billing not configured (dev / self-host) → use the default env credential
    with no metering. Unreachable on a billing-enabled shared server: setting
    ``PENNY_SUBSIDY_PROVIDER_KEY`` turns on the subsidy gate below."""


@dataclass(frozen=True, slots=True)
class UseByo:
    """Run on the user's own connected credential (no subsidy accounting)."""

    credential: Credential


@dataclass(frozen=True, slots=True)
class UseSubsidy:
    """Run on the platform key; accrue each completion to the ledger."""

    platform_key: str


@dataclass(frozen=True, slots=True)
class Blocked:
    """Runway exhausted and no BYO — the turn does not reach the model."""

    reason: str


GateDecision = UseDefault | UseByo | UseSubsidy | Blocked


def billing_enabled() -> bool:
    """Metered billing is on iff a platform subsidy key is configured.

    Config-driven, not topology-driven (AGENTS.md): production sets
    ``PENNY_SUBSIDY_PROVIDER_KEY`` and the gate enforces the subsidy runway;
    dev/self-host leaves it unset and chat runs on the default env key.
    """
    return bool(subsidy_provider_key())


def resolve_for_run(
    session: Session,
    ctx: RequestContext,
    *,
    provider: str = ACTIVE_PROVIDER,
) -> GateDecision:
    """Decide how to credential this run. See module docstring for the arms.

    ``session`` must be an owner-bound billing session (``BillingSession``); the
    vault + metering reads share it so the whole decision is one consistent read.
    """
    byo = vault.get_credential(session, ctx, provider=provider)
    if byo is not None:
        return UseByo(byo)
    if not billing_enabled():
        # Dev/self-host: no metered subsidy configured, run on the default key.
        return UseDefault()
    if metering.remaining_cents(session, ctx) > 0:
        return UseSubsidy(subsidy_provider_key())
    # Fail closed: no BYO and no runway — never reach for an ambient env key.
    return Blocked("subsidy runway exhausted; connect a provider to continue")


def grant_subsidy_on_plaid_link(session: Session, ctx: RequestContext) -> bool:
    """Grant the per-user subsidy on a genuine-intent Plaid link (idempotent).

    Penny's subsidy policy, deliberately separate from the generic gate. The
    call site is the **website-owned** Plaid exchange (phase 5); it is not the
    agent ``connect_new_account`` tool (agent code may not import billing).
    Returns whether the grant was newly applied.
    """
    return metering.grant_subsidy(session, ctx, cents=subsidy_cents())
