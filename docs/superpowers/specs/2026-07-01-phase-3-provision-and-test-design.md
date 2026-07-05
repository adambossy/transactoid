# Phase 3 — Provision + Test — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-01
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** [Phase 1a](../plans/2026-06-27-phase-1a-multi-tenant-data-model.md),
[Phase 1b](../plans/2026-06-27-phase-1b-workspace-hybrid.md),
[Phase 2](2026-07-01-phase-2-auth-social-login-design.md)

## Goal

Stand up the two real users in one household and validate the whole multi-tenant
+ auth stack against real financial data, end to end — the first time real money
data flows through the isolated path. Phase 3 is mostly a **runbook plus an
acceptance definition**, with one real code deliverable: an idempotent admin CLI
for provisioning before the signup UI (phase 4) exists.

## Decisions (locked)

- **Provisioning:** an **idempotent admin CLI** (`penny admin …`), reusing phase
  1a's `backfill_household` helper. Auditable, repeatable, safe to re-run.
- **Environment:** run the backend **locally** (so Plaid Link's localhost flow
  works) against the **Neon `penny-test` branch first (rehearse), then prod
  (execute)**. Clerk dev instance locally. The remote Plaid-redirect
  rearchitecture (productionization B-6) is deferred to phase 5/onboarding.
- **Leakage validation:** cross-household isolation is proven by **phase 1a's
  automated two-household suite** (synthetic households A/B); **real data** is
  used to validate within-household privacy and joint (shared-only) end to end.

## Components

### Admin CLI (the code deliverable)

New `penny admin` command group (Typer, in `cli.py` or a new `penny/admin.py`),
each command idempotent and available only when explicitly run (not exposed over
HTTP):

- `create-household --name` → creates/returns a `households` row.
- `create-user --household <id> --email` → creates a `users` row (lowercased
  email); `external_auth_id` stays null until first Clerk login (phase 2 links
  it). Re-running with an existing email is a no-op that prints the id.
- `list-accounts --household <id>` → lists `plaid_accounts` with owner +
  visibility, so you can see what to flip.
- `set-account-visibility --account <id> --visibility private|shared` → flips a
  `plaid_accounts` row (and the denormalized copies) in one transaction.

These reuse phase 1a's `backfill_household` / façade write paths and run under an
explicit admin `RequestContext` (or a maintenance connection) so RLS is
satisfied.

### Provisioning runbook

1. Rehearse the whole sequence on the **`penny-test`** branch, then repeat on
   **prod**.
2. `create-household` (yours) + `create-user` ×2 (you, wife). Invite both emails
   in Clerk (allowlist).
3. Each spouse logs in locally via Clerk → first-login email linking populates
   `external_auth_id` (phase 2).
4. Confirm the phase-1a backfill assigned your existing data to your household /
   you as owner / `visibility='private'`.
5. Each spouse links their own banks via the local Plaid Link flow; set
   per-account visibility (default private; `set-account-visibility … shared`
   for the intended shared accounts). `list-accounts` to verify.

### Acceptance checklist (what proves "no leakage")

- **Cross-household:** phase 1a's two-household leakage suite is green against the
  prod schema/config (synthetic A/B).
- **Within-household privacy (real data):** in an individual session, each spouse
  sees own private + shared; the **other spouse's private accounts/transactions
  are absent** — verified via UI, and via a direct `run_sql` probe from each
  spouse's context.
- **Joint session (real data):** a joint conversation returns **shared-only** —
  neither spouse's private transactions, memories, or reports appear.
- **Conversations:** a spouse cannot open the other's individual conversation
  (403/404); joint threads are visible to both.
- **Cron:** each per-user individual report is correctly scoped and reaches only
  that user; the household shared report is shared-only and reaches both.
- **Workspace (phase 1b):** real agent runs materialize, write back, and version
  correctly; a joint run never resolves a private prefix.
- **Secrets:** `plaid_items.access_token` is ciphertext at rest; no token in
  logs.

## Testing strategy

- The automated phase-1a/1b/2 suites (Postgres-marked) run green against the
  prod-equivalent config on the `penny-test` branch before prod execution.
- The real-data acceptance checklist above is executed manually (with `run_sql`
  probes) and recorded as a completion artifact.

## Out of scope

- Self-serve signup UI (phase 4) and guided onboarding (phase 5).
- Remote Plaid-redirect rearchitecture (B-6) — phase 3 links banks locally.
- Any new isolation mechanism — phase 3 only exercises what 1a/1b/2 built.
