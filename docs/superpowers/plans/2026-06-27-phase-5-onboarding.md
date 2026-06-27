# Phase 5 — Onboarding (Plan Stub)

> **Status: Roadmap — needs brainstorming before a detailed plan.**
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [foundation design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 4 — Signup UI](2026-06-27-phase-4-signup-ui.md) ·
> **Next:** [Phase 6 — Security audit](2026-06-27-phase-6-security-audit.md)

**Goal:** Guide a new household from empty to productive — banks linked,
taxonomy tuned, merchant rules established, first sync done.

**Depends on:** Phase 2 (auth) and Phase 4 (signup/household bootstrap).

## Scope (to be refined in brainstorming)

- Guided **Plaid linking** (note the gotcha: `connect_new_account` runs a
  localhost HTTPS server + browser — remote deployment needs the redirect
  rearchitecture from the productionization plan, B-6). This phase likely
  depends on that rework.
- Per-account **visibility** choices during linking (private vs shared).
- **Taxonomy** customization on top of the seeded default.
- **Merchant-rule** setup, including private-account-scoped rules.
- First-sync experience and progress feedback.

## Key questions for brainstorming

- Does Plaid redirect rearchitecture (B-6) block this phase, or can onboarding
  ship with the localhost flow for the two of you first?
- How much taxonomy/rule setup is guided vs. deferred to the chat agent?

## Security focus

- Visibility defaults during linking (default private, opt-in to shared).
- Plaid token handling at link time (encryption from phase 1 must be in the path).
