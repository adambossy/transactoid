# Phase 3 — Provision the Two Accounts + Test (Plan Stub)

> **Status: Roadmap — needs brainstorming before a detailed plan.**
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [foundation design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 2 — Auth / social login](2026-06-27-phase-2-auth-social-login.md) ·
> **Next:** [Phase 6 — Security audit](2026-06-27-phase-6-security-audit.md)

**Goal:** Stand up the two real users in one household and validate the whole
multi-tenant + auth stack against real financial data, end to end.

**Depends on:** Phase 1 (data model) and Phase 2 (real auth).

## Scope (to be refined in brainstorming)

- Create the household + two `users` (you + wife) in production.
- Confirm the phase-1 migration correctly assigned your existing data to your
  household with `visibility='private'`; flip the intended accounts to `shared`.
- Each of you links your own banks; set per-account visibility.
- Exercise individual sessions (own-private + shared) and joint sessions
  (shared-only) against real data.
- Validate workspace materialization, write-back, and version history with real
  agent runs.

## Key questions for brainstorming

- How is the household + users bootstrapped in prod before the signup UI exists
  (phase 4)? Script vs. one-off admin path.
- Acceptance checklist: what concretely proves "no leakage" with real data?

## Security focus

- This is the first time real financial data flows through the multi-tenant
  path. Run the leakage/privacy/joint-session suites against the real dataset.
