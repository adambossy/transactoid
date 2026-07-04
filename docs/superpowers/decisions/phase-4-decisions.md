# Phase 4 — Signup / Account-Creation UI — Implementation Decisions

Fail-closed / security-relevant choices made while executing
`docs/superpowers/plans/2026-07-02-phase-4-signup-ui.md`. This file is owned by
the phase-4 implementation session; it records decisions the plan/spec left
open.

## D1 — `households`/`users` live in the finance schema, not a `web.*` schema

The orchestrator brief described signup as "website-domain code using the
website's own Base/schema." The **canonical plan** (Task 1) instead provisions
`Household`/`User` via the finance facade models (`penny.adapters.db.models`)
and seeds the taxonomy through `penny.bootstrap.seed_taxonomy_for_household`.
Reconciliation: phase-1a deliberately placed `households`/`users` in the finance
DB because they are the **tenancy backbone** — every finance row FKs to
`household_id` and RLS is enforced on that schema. They are not app-owned data
(conversations, billing) that must be kept out of `run_sql`'s blast radius. So
`signup.py` follows the plan verbatim and uses the finance models. The
website/agent segregation that matters here is preserved: `signup.py` is invoked
only by website code (auth dependency + routes); no agent tool/skill imports it
(the `test_domain_segregation` guardrail continues to pass).

## D2 — Routes live in a dedicated `penny/api/signup_routes.py` router

The plan says "modify `api/main.py` — new routes." To keep the shared `main.py`
edit minimal/localized (orchestrator constraint) and to match the existing
`billing_routes.py` router pattern, the new `/api/me`, `/api/invites`,
`/api/household` routes live in a new `penny/api/signup_routes.py` `APIRouter`,
mounted with a single `app.include_router(...)` line in `main.py`. This is the
same "wire the routes into the app" outcome the plan intends, with a smaller and
more consistent shared-file diff.

## D3 — Invite creation is fail-closed on the pre-existing-account check

`create_invite` rejects (`InviteError` → HTTP 409) when **any** `users` row with
that email already has `external_auth_id` set (an active account), so an invite
can never target / hijack an already-linked identity. A pending row
(`external_auth_id IS NULL`) is re-used idempotently and never duplicated.

## D4 — `household_id` is never read from a request body

Every invite/household mutation derives the tenant from `ctx.household_id` (the
verified principal), never from the request payload — an inviter can only ever
write into their own household. `revoke_invite` and `rename_household` filter on
`ctx.household_id` so a caller cannot touch another household's rows even by
guessing an email/name.

## D5 — `revoke_invite` only deletes pending rows, never active users

`revoke_invite` filters `external_auth_id IS NULL` in addition to the household +
email match, so revoking an invite can never delete a user who has already
claimed it (become active). If the row is already claimed/absent it is a no-op
(idempotent, error defined out of existence).

## D7 — Auto-provision requires a **verified** email; unverified fails closed

The spec amends phase-2's unknown-user branch from 403 → auto-provision. The
implementation keeps phase-2's `link_or_resolve_user` as the primary resolver
(it does the by-sub lookup and the `email_verified`-guarded, row-locked pending
claim), and only on `UnknownUserError` calls `resolve_or_provision_identity` —
**and only when the token's email is verified**. An unverified/absent email
still returns 403 ("unverified identity"), so an account is never provisioned on
an email the caller has not proven they own. Phase-2's `test_auth_e2e` /
`test_auth_dependency` 403 cases were updated: verified-unknown now provisions
(200), and a new unverified-unknown case asserts the 403.

## D6 — Idempotency under a signup race is DB-backed

`provision_solo_household` checks for an existing user by email first (fast
path), and the `users.email` UNIQUE constraint is the backstop: two concurrent
first-logins for the same email cannot both create a household+user. The
pending-invite claim in `resolve_or_provision_identity` uses the same atomic
`UPDATE ... WHERE external_auth_id IS NULL` first-login link phase-2 established.
