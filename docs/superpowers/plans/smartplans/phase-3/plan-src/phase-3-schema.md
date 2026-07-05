---
id: phase-3-schema
label: Schema reconciliation
parent: phase-3
sections: [reconcile, create-all-fix]
crosslinks: [phase-3-assign]
---

# Schema reconciliation

Production is `create_all`-managed with a multi-head alembic history, so a plain upgrade is unsafe. This stage brings alembic and the real schema into agreement, then applies the multi-tenant migration chain.

## Requirements

- My production database is upgraded to the new multi-tenant structure without losing or corrupting any existing data.
- The upgrade is rehearsed on a throwaway copy first, so surprises surface before production is touched.
- After the fix, future schema changes stay disciplined and cannot silently drift out of sync again.

## reconcile — Reconciling alembic with reality

On a throwaway Neon branch off production: resolve the **legacy** multi-head history to a single head by merging the branches, then stamp the revision that matches production's current `create_all` schema so alembic believes the baseline is already applied. The new epic migrations are one linear chain per the ledger, so the only multi-head to reconcile is the legacy one — the epic manufactures none. The chain is then applied in **two halves around the data assignment**: upgrade to the expand point (identity tables, `plaid_accounts`, nullable columns) first, then bootstrap and assign and re-parent, then upgrade the rest (the NOT-NULL/RLS contract, workspace, conversations) — because the contract can only land once every legacy row has an owner. Crucially, **prod identity and ownership are created here, not by any migration**: the dev-only backfill is a no-op on production. Rehearse the whole sequence on the branch, confirm the schema and a smoke query, then repeat on production behind the pre-apply snapshot.

## create-all-fix — Fixing create_all for good

Reconciliation is a one-time fix; three disciplines keep it fixed. Production's bootstrap runs an alembic upgrade only — `create_all` stays for local SQLite development but never runs against production. Every future schema change ships as a migration, and migration branches are merged to keep a single head. A continuous-integration drift guard — an empty autogenerate diff — catches regressions, wired into the Phase-6 CI job. Without these, `create_all` drift would simply return; with them, the reconciliation sticks. Next: [assignment and handoff](assign.html).
