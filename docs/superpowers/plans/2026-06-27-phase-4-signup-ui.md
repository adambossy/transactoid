# Phase 4 — Signup / Account-Creation UI (Plan Stub)

> **Status: Planned** — see the [Phase 4 spec](../specs/2026-07-02-phase-4-signup-ui-design.md) and the [detailed plan](2026-07-02-phase-4-signup-ui.md).
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 4 design](../specs/2026-07-02-phase-4-signup-ui-design.md) · foundation: [phase 1a design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 2 — Auth / social login](2026-06-27-phase-2-auth-social-login.md) ·
> **Next:** [Phase 5 — Onboarding](2026-06-27-phase-5-onboarding.md)

**Goal:** Let a new (invited) user create an account and bootstrap a household
through the UI, instead of being provisioned by hand.

**Depends on:** Phase 2 (auth). Independent of phase 3.

## Scope (to be refined in brainstorming)

- Signup flow gated to invited emails (still you + wife class of users).
- Household bootstrap on first signup: create `households` row, seed taxonomy
  from `configs/taxonomy.yaml`, create the user's private workspace prefix.
- Joining an existing household (invite a spouse to your household) vs. creating
  a new one.
- Frontend account-creation screens.

## Key questions for brainstorming

- Invite model: invite-code, email allow-list, or admin-creates-then-user-claims?
- Does signup create a new household or join an existing one — and how is "join
  my spouse's household" expressed? (This is where one-household-per-user may
  need to relax toward membership.)
- What seeds at creation time (taxonomy now; merchant rules in onboarding)?

## Security focus

- Account-creation is an unauthenticated-ish entry point; abuse/allow-list
  enforcement, and ensuring a new household is fully isolated from creation.
