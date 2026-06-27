# Phase 1b — Workspace Hybrid (R2 + Postgres Manifests) (Plan Stub)

> **Status: Designed in the spec — needs a detailed bite-sized plan.**
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [foundation design — Workspace section](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 1a — Multi-tenant data model](2026-06-27-phase-1a-multi-tenant-data-model.md) ·
> **Next:** [Phase 2 — Auth / social login](2026-06-27-phase-2-auth-social-login.md)

**Goal:** Move the per-household workspace (memory, rules, reports) off the local
filesystem onto the hybrid store — Postgres+RLS as capability broker, R2 as blob
store — with manifest versioning and atomic compare-and-set write-back.

**Depends on:** Phase 1a (`RequestContext`, RLS, identity tables, visibility
model must exist). Until 1b lands, memory/reports live on the per-household
filesystem path introduced in 1a.

## Scope (design is in the spec; plan to be written)

- **Extend the R2 adapter** (`penny/adapters/storage/r2.py`) — currently only
  `store_object_in_r2` / `download_object_from_r2` / `make_artifact_key`. Needs
  list-by-prefix, delete, and object-version handling.
- **Pointer + manifest schema** — per-household/per-user prefix pointer rows and
  append-only manifest rows, under the same RLS policy as 1a; opaque
  high-entropy directory tokens.
- **Capability-broker lookup** — RLS-gated read returns only the prefixes the
  current principal + `session_mode` may read (joint → shared-only).
- **Materialize → temp dir** — sync allowed R2 object versions to a per-run temp
  dir (torn down after; excluded from logs).
- **Flush + atomic CAS** — upload changed blobs to R2 first, then a single
  compare-and-set on the household workspace head; re-materialize + retry on
  conflict. Visibility-routed write-back; new-file default private/shared by
  session mode.
- **Memory loader wiring** — `{{AGENT_MEMORY}}` injection reads from the
  materialized temp dir per session mode.
- **Workspace test suite** — joint never resolves private prefixes; concurrent
  flush CAS (one wins, loser retries, no lost update); aborted run commits
  nothing.

## Key questions for the plan

- R2 object-versioning vs. content-addressed immutable keys for blob history.
- Conflict re-apply strategy for markdown (3-way merge vs. append-only files).
- Where the workspace head pointer lives (dedicated table) and its CAS mechanism
  (`UPDATE … WHERE head = :parent` vs. unique `(workspace_id, parent)`).

## Security focus

- The R2 access path is the explicit phase-6 audit item: opaque tokens, no-`LIST`
  scoped credentials, app-derives-keys-only-from-RLS-lookups, no direct agent R2
  capability.
