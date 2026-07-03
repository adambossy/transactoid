---
id: phase-3-schema
label: Schema reconciliation
parent: phase-3
sections: [reconcile, create-all-fix]
crosslinks: [phase-3-assign]
---

# Schema reconciliation

Production is `create_all`-managed with a multi-head alembic history, so a plain upgrade is unsafe. This stage brings alembic and the real schema into agreement, then applies the multi-tenant migration chain.

## reconcile — Reconciling alembic with reality

On a throwaway Neon branch off production: resolve the multi-head history to a single head by merging the branches, then stamp the revision that matches production's current `create_all` schema so alembic believes the baseline is already applied, then upgrade to run only the new revisions — phase 1a's identity/tenancy migrations, phase 1b's workspace tables, phase 2's conversation columns, and the cutover's own data steps. Rehearse the whole stamp-and-upgrade on that branch, confirm the schema and a smoke query, then repeat on production behind the pre-apply snapshot.

## create-all-fix — Fixing create_all for good

Reconciliation is a one-time fix; three disciplines keep it fixed. Production's bootstrap runs an alembic upgrade only — `create_all` stays for local SQLite development but never runs against production. Every future schema change ships as a migration, and migration branches are merged to keep a single head. A continuous-integration drift guard — an empty autogenerate diff — catches regressions, wired into the Phase-6 CI job. Without these, `create_all` drift would simply return; with them, the reconciliation sticks. Next: [assignment and handoff](assign.html).
