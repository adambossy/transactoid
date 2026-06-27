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
| 1 | [Multi-tenant data model](2026-06-27-phase-1-multi-tenant-data-model.md) | — | **Designed** (spec complete); plan in progress |
| 2 | [Auth / social login](2026-06-27-phase-2-auth-social-login.md) | 1 | Roadmap — needs brainstorming |
| 3 | [Provision + test the two accounts](2026-06-27-phase-3-provision-and-test.md) | 1, 2 | Roadmap — needs brainstorming |
| 4 | [Signup / account-creation UI](2026-06-27-phase-4-signup-ui.md) | 2 | Roadmap — needs brainstorming |
| 5 | [Onboarding](2026-06-27-phase-5-onboarding.md) | 2, 4 | Roadmap — needs brainstorming |
| 6 | [Security audit](2026-06-27-phase-6-security-audit.md) | 1–5 | Roadmap — needs brainstorming |

## Dependency graph

```
1 ──┬─► 2 ──┬─► 3
    │       ├─► 4 ──► 5
    │       │
    └───────┴──────────► 6 (audits everything built in 1–5)
```

## Status legend

- **Roadmap — needs brainstorming:** scope captured; run the brainstorming skill
  to produce a spec, then writing-plans to produce a no-placeholder plan.
- **Designed:** spec complete and approved.
- **Plan in progress / complete:** bite-sized implementation plan being written.
