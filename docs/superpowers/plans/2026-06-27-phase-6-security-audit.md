# Phase 6 — Security Audit (Plan Stub)

> **Status: Planned** — see the [Phase 6 spec](../specs/2026-07-03-phase-6-security-audit-design.md) and the [detailed plan](2026-07-03-phase-6-security-audit.md).
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 6 design](../specs/2026-07-03-phase-6-security-audit-design.md) · foundation: [phase 1a design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 5 — Onboarding](2026-06-27-phase-5-onboarding.md)

**Goal:** Intensely audit the whole system so personal financial data cannot
leak across households or between spouses, before/while real data is in use.

**Depends on:** Phases 1–5 (audits everything built).

## Scope (to be refined in brainstorming)

- **Cross-tenant leakage:** adversarial review of every façade method + a battery
  of `run_sql` queries; confirm RLS holds under all paths.
- **RLS policy audit:** verify every per-household table has the correct policy
  and the join-free denormalized columns stay consistent.
- **R2 access path** (explicit focus): RLS protects the pointer, not the bytes —
  verify opaque tokens, no-`LIST` scoped credentials, app-derives-keys-only-from-
  RLS-lookups, and no direct agent R2 capability.
- **Workspace concurrency:** CAS atomicity, no lost updates, temp-dir
  teardown/hygiene, no private bytes in joint temp dirs.
- **Secret handling:** Plaid-token encryption at rest + in logs; key management.
- **Prompt injection:** attempt to coerce the agent's `run_sql` / tools into
  cross-tenant reads; confirm RLS backstops it.
- **Transport / dependencies:** CORS, TLS, auth token validation, dependency CVEs.

## Key questions for brainstorming

- Use the `rook` agent and `/security-review` skill as the audit harness?
- Which findings are blocking vs. tracked-for-later?
- Do we engage an external review given real financial data?

## Security focus

- This phase *is* the security focus. Output: a findings report with severity
  tiers and a remediation plan.
