# Phase 2 — Auth / Social Login (Plan Stub)

> **Status: Planned** — see the [Phase 2 spec](../specs/2026-07-01-phase-2-auth-social-login-design.md) and the [detailed plan](2026-07-02-phase-2-auth-social-login.md).
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 2 auth design](../specs/2026-07-01-phase-2-auth-social-login-design.md) · foundation: [phase 1a design](../specs/2026-06-27-multi-account-foundation-design.md).
> **Prev:** [Phase 1 — Multi-tenant data model](2026-06-27-phase-1-multi-tenant-data-model.md) ·
> **Next:** [Phase 3 — Provision + test](2026-06-27-phase-3-provision-and-test.md),
> [Phase 4 — Signup UI](2026-06-27-phase-4-signup-ui.md)

**Goal:** Replace phase 1's dev-stub principal with real, verified identity from
a social-login provider (Google), gated to you + your wife.

**Depends on:** Phase 1 (the `RequestContext { user_id, household_id,
session_mode }` contract and `users.external_auth_id` column must exist).

## Scope (to be refined in brainstorming)

- Choose **Clerk vs Auth0** (key decision).
- Google sign-in; allow-list limited to two emails.
- FastAPI auth middleware: verify JWT → resolve `external_auth_id` → load
  `users` row → build `RequestContext`. Reject unknown subjects (401/403).
- Frontend: login screen, token storage, attach `Authorization` header on
  `/api/chat` and all API calls; replace the localStorage session-id model.
- Map provider subject → `users.external_auth_id`; first-login linking.
- Lock down CORS (currently allows all origins).

## Key questions for brainstorming

- Clerk vs Auth0 (DX, pricing, self-host, session model).
- Where does session_mode (individual vs joint) get chosen in the UI/auth flow?
- Token lifetime / refresh strategy; backend session persistence implications.

## Security focus

- No data-layer changes — the boundary already exists. The risk surface is the
  middleware: a bug that resolves the wrong `RequestContext` would mis-scope RLS.
- CORS, token validation, allow-list enforcement.
