# Phase 4 — Signup / Account-Creation UI — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-02
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** [Phase 2 — Auth](2026-07-01-phase-2-auth-social-login-design.md)
(and [Phase 1a](../plans/2026-06-27-phase-1a-multi-tenant-data-model.md) taxonomy
seeding + [Phase 1b](../plans/2026-06-27-phase-1b-workspace-hybrid.md) workspace
prefixes)

## Goal

Let anyone sign up self-serve (each new signup gets an isolated one-person
household), and let a household member invite **new** people who then sign up
directly into that household — without the complexity of household merge or
multi-household membership.

## Decisions (locked)

- **Fully open self-serve signup.** A verified Clerk user with no `users` row is
  auto-provisioned a **new solo household**. This **replaces phase 2's
  unknown-user 403** (see Amendments).
- **Invites are for new (accountless) users only.** They sign up directly into
  the inviter's household. An email that already belongs to an active account
  cannot be invited — messaging tells them to create a fresh account.
- **One individual = one household** (invariant preserved). No merge, no
  many-to-many membership. Someone wanting into another household starts fresh
  and can **re-link the same bank** via Plaid (independent links per household).
- The solo-household **re-parent** alternative (for existing users) is recorded
  as deferred future work to revisit if "new users only" proves limiting.

## Architecture

Phase 2 already turns a verified JWT into a `RequestContext`. Phase 4 changes one
thing in that resolution — the **unknown-user branch** — and adds an invite
surface. Everything else (RLS, scoping) is unchanged.

Identity resolution (extends phase 2):

1. Verified token → resolve `users` by `external_auth_id`, else by verified
   lowercased email (first-login linking).
2. **Match found** → build `RequestContext` as today.
3. **No match, pending invite row exists for this email** → link the Clerk
   subject into that pending row's household (join).
4. **No match, no pending row** → **auto-provision**: create household + user +
   seed taxonomy + workspace prefixes (below), then build the context.

## Auto-provision (new solo household)

In one transaction, on first sight of an un-invited verified user:

- `households` row (`name` defaults to e.g. `"<email-local-part>'s household"`,
  editable later).
- `users` row (`household_id`, lowercased `email`, `external_auth_id = sub`).
- Seed taxonomy via phase-1a's `seed_taxonomy_for_household(session, household_id)`.
- Create the household's workspace prefixes / initial manifest (phase-1b).

Idempotent: a race or retry that finds the row already created is a no-op.

## Invite flow (new users only)

- `POST /api/invites` (authenticated) — body `{email}`. The caller invites into
  **their own** household (`ctx.household_id`); `household_id` is never taken
  from the request.
- Server: lowercase the email; **reject** if an active `users` row already has
  it (`external_auth_id` set) → `409` with start-fresh messaging. Otherwise
  create a **pending `users` row** (`household_id = ctx.household`, email,
  `external_auth_id = NULL`) and issue a **Clerk invitation** (native email +
  restricts that email's signup). Idempotent on a pending email.
- On the invitee's first login, phase-2 linking (step 3 above) finds the pending
  row by email and links them into that household instead of auto-provisioning.
- `GET /api/invites` (authenticated) lists this household's pending invites;
  `DELETE /api/invites/{email}` revokes (removes the pending row + Clerk
  invitation).

## Frontend

- Clerk `<SignUp>` / `<SignIn>` (Google). After auth, the app calls a bootstrap
  endpoint (`GET /api/me`) that ensures the user's household exists (triggers
  auto-provision on first call) and returns `{user, household}`.
- **Invite screen** (household members): enter an email → `POST /api/invites`;
  show pending invites with revoke. Clear messaging for the
  already-has-an-account case (`409`).
- Household name is shown and editable (a simple `PATCH /api/household`).

## UI/UX Requirements

- As a prospective user, I can reach a self-serve signup screen (Clerk
  `<SignUp>`) rendered inside the normal app shell, sign up with Google, and land
  directly in my own solo household.
- As a newly signed-up user, I see my household's name in the header, and I can
  click it to rename the household inline (persisted via `PATCH /api/household`).
- As a household member, I can open an Invite screen, enter an email address, and
  send an invitation; the screen lists my household's pending invites, each with a
  revoke control.
- As an inviter, when I try to invite an email that already has an account, I see
  a clear message telling me they must sign up fresh (the `409` "start fresh"
  case), rather than a generic error.
- As a member of a brand-new household with no synced data yet, I see a friendly
  empty state that explains what to do next instead of a blank or broken screen.

All new screens use the **shared UI template primitives** (Header, Footer, Logo,
color tokens, type scale, font stack) — no bespoke styling. Screens are
responsive (mobile and desktop) and handle loading, empty, and error states, and
the app shell (header/footer) is consistent across screens.

## Amendments to phase 2

- The auth dependency's **unknown-user branch changes from `403` to
  auto-provision** (open signup). The "allowlist = the `users` table" gate from
  phase 2 no longer applies once phase 4 ships; the `users` table is populated by
  signup, not by pre-provisioning. `/api/me` and `/api/invites` are new
  authenticated routes under the same dependency.

## Security

- **Open-signup abuse surface:** anyone can create accounts and initiate Plaid
  links (cost/abuse). Mitigations to add and/or track: rate-limit signup and
  Plaid-link initiation per identity/IP; monitor Plaid usage. Flagged as a
  **phase-6 audit item**.
- **Invite safety:** invites target only the caller's own household; cannot
  target an already-active email (no account takeover); the invitee must verify
  the same email through Clerk; pending rows carry no privileges until linked.
- **Isolation:** two independent signups yield two fully isolated households
  (phase-1a RLS). Re-linking the same bank in two households produces independent
  `plaid_items` — no shared rows.

## Testing strategy

Postgres-marked where RLS is involved.

- **Auto-provision:** a new verified user with no row gets a solo household +
  seeded taxonomy + workspace; two independent signups are mutually invisible
  (leakage suite).
- **Invite → join:** an invited email signs up and lands in the **inviter's**
  household (not a new one), seeing that household's shared data per visibility.
- **Invite guards:** inviting an already-active email → `409`; invite targets
  only `ctx.household`; a revoked invite no longer links on signup.
- **Idempotency:** concurrent first-login requests provision exactly one
  household; re-invite of a pending email is a no-op.
- **Re-link:** the same bank linked from two households yields independent items;
  neither household sees the other's transactions.

## Out of scope

- Household merge and multi-household membership (dropped; re-parent recorded as
  future work).
- Guided onboarding (Plaid linking UX, taxonomy tuning, merchant rules) — phase 5.
- Signup gating / waitlist (signup is fully open) and paid tiers.

## Future work

- **Solo-household re-parent on join:** allow inviting an existing user **iff**
  their household is solo — on accept, re-parent their accounts/transactions into
  the inviter's household (`UPDATE household_id`, remap `category_id` by key) and
  retire the empty solo household. Preserves legacy data without merge or
  many-to-many. Revisit if "new users only" proves limiting.
