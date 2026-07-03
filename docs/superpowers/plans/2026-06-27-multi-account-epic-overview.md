# Multi-Account Epic — Plan Index

> Linked index for the multi-account epic. Each phase is its own plan with its
> own spec → plan → build cycle. This page is the map; follow the links.

**Design spec:** [`../specs/2026-06-27-multi-account-foundation-design.md`](../specs/2026-06-27-multi-account-foundation-design.md)

## Principles carried across all phases

- **Security at each step**, not only phase 6. Each phase carries its own
  security work (e.g. Plaid-token encryption lands in phase 1).
- **Strict-first isolation.** User-centric RLS from day one; loosening later is
  a one-line policy change, tightening later is a risky migration.
- **The data layer is auth-agnostic.** Everything reads a `RequestContext`;
  phase 1 stubs it, phase 2 fills it with real auth — no data-layer churn.

## Phases

| # | Plan | Depends on | Design status |
|---|------|-----------|---------------|
| 1a | [Multi-tenant data model (tenancy + RLS + encryption)](2026-06-27-phase-1a-multi-tenant-data-model.md) | — | **Designed**; plan complete |
| 1b | [Workspace hybrid (R2 + Postgres manifests)](2026-06-27-phase-1b-workspace-hybrid.md) | 1a | **Planned** ([plan](2026-07-02-phase-1b-workspace-hybrid.md)) |
| 2 | [Auth / social login](2026-06-27-phase-2-auth-social-login.md) | 1a | **Planned** ([spec](../specs/2026-07-01-phase-2-auth-social-login-design.md) · [plan](2026-07-02-phase-2-auth-social-login.md)) |
| 2b | [BYO keys & metered subsidy](../specs/2026-07-03-phase-2b-byo-keys-metered-subsidy-design.md) | 2 (+ agent-harness) | **Designed** ([spec](../specs/2026-07-03-phase-2b-byo-keys-metered-subsidy-design.md)); needs plan. **Prerequisite for phase 4** open signup (spend cap) |
| 0 | [Design system (shared UI template)](2026-07-03-phase-0-design-system.md) | — | **Reference received** ([design-reference/](../../../frontend/design-reference/)); ready to spec; precedes UI phases 2/4/5 |
| 3 | [Production cutover & legacy-data migration](2026-06-27-phase-3-provision-and-test.md) *(repurposed)* | 1a, 1b, 2 | **Designed** ([spec](../specs/2026-07-03-phase-3-cutover-design.md)); needs plan. Old provision+test docs superseded (provisioning→4, validation→6) |
| 4 | [Signup / account-creation UI](2026-06-27-phase-4-signup-ui.md) | 2, **2b** | **Planned** ([spec](../specs/2026-07-02-phase-4-signup-ui-design.md) · [plan](2026-07-02-phase-4-signup-ui.md)); open signup gated on 2b's spend cap |
| 5 | [Onboarding](2026-06-27-phase-5-onboarding.md) | 2, 4 | **Planned** ([spec](../specs/2026-07-03-phase-5-onboarding-design.md) · [plan](2026-07-03-phase-5-onboarding.md)) |
| 6 | [Security audit](2026-06-27-phase-6-security-audit.md) | 1a–5 | **Planned** ([spec](../specs/2026-07-03-phase-6-security-audit-design.md) · [plan](2026-07-03-phase-6-security-audit.md)) |

## Dependency graph

```
1a ──► 1b ──┐
 │          │
 └─► 2 ──┬─► 2b ──► 4 ──► 5
         ├─► 3
         │
1a─1b────┴──────────────► 6 (audits everything built in 1a–5, 2b)
```

Note: **2b (BYO keys & metered subsidy)** sits between 2 and 4 — open self-serve
signup (4) must not ship without 2b's per-user spend cap. It also requires an
**agent-harness** change (token counting + credential resolver).

## Status legend

- **Roadmap — needs brainstorming:** scope captured; run the brainstorming skill
  to produce a spec, then writing-plans to produce a no-placeholder plan.
- **Designed:** spec complete and approved.
- **Plan in progress / complete:** bite-sized implementation plan being written.
