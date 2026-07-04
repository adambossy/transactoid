# Phase 3 — Production Cutover & Legacy-Data Migration

> **Status: Planned** — see the [Phase 3 cutover spec](../specs/2026-07-03-phase-3-cutover-design.md) and the [detailed plan](2026-07-03-phase-3-cutover.md).
> Repurposed from "Provision + test": provisioning → [Phase 4](2026-06-27-phase-4-signup-ui.md);
> real-data validation → [Phase 6](2026-06-27-phase-6-security-audit.md); the
> household/user admin CLI becomes a minor Phase-4 utility. What remains is the
> **one-time production cutover and legacy-data migration** (this phase).
>
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> **Superseded docs** (kept for reference): old
> [provision+test spec](../specs/2026-07-01-phase-3-provision-and-test-design.md) ·
> [plan](2026-07-01-phase-3-provision-and-test.md).

## New scope (to be specced)

A fully **programmatic, account-aware** cutover:

1. Apply the multi-tenant migration chain to the real prod DB safely (prod is
   `create_all`-managed with multi-head alembic history — see the
   `project_prod_alembic_create_all` note).
2. Create the household + **pending** user rows (you + wife;
   `external_auth_id` NULL) so Phase-4 first-login linking claims them.
3. **Enumerate the linked accounts** in the legacy single-user data; per account,
   assign **owner** (you vs wife) and **visibility** (private/shared) from a
   mapping you supply.
4. Re-parent every transaction/item to the household, deriving `owner_user_id`
   and `visibility` from each row's account assignment.
5. Handoff: you sign up → claim pending-you; wife signs up → claim pending-her;
   shared accounts visible to both.

**Amendment to Phase 1a:** its generic backfill (migration 009) stays the simple
dev/test default (all rows → one owner, private); the real prod backfill is this
account-aware cutover, and the seeded users are **pending** (no
`external_auth_id`) so signup claims them.
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
