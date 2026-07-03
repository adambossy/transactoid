# Phase 2 — Auth / Social Login — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-01
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** [Phase 1a — Multi-tenant data model](../plans/2026-06-27-phase-1a-multi-tenant-data-model.md)

## Goal

Replace phase 1a's dev-stub principal with real, verified identity from Clerk
(Google social login), gated to two invited spouses, without changing the data
layer — everything already reads a `RequestContext`. Phase 2 wires that context
to a verified JWT, scopes conversations to the household, hardens the cron path,
and closes the auth/CORS/`run_sql` holes surfaced in security review.

## Decisions (locked)

- **Provider:** Clerk (Google login). JWTs verified server-side via JWKS.
- **No user creation in phase 2:** users exist (provisioned in phase 3); phase 2
  **links** a Clerk identity to an existing `users` row by verified email.
- **Allowlist = the `users` table.** An authenticated Clerk user with no matching
  row is rejected 403.
- **Session mode stays binary** (`individual | joint`), **per-conversation and
  immutable**. The participant-set generalization is deferred (see Future work).
- **`run_sql` goes read-only** in phase 2 (dedicated read-only DB role for the
  free-form SQL path); curated `@tool` writes keep a normal RLS-scoped connection.
- **Cron** builds an explicit `RequestContext` per job and fails closed if its
  principal is unset.

---

## Architecture

Clerk authenticates the user in the browser and issues a JWT. A FastAPI
dependency verifies the JWT, resolves it to a `users` row, builds the phase-1a
`RequestContext{user_id, household_id, session_mode}`, and sets the phase-1a
ContextVar for the request. From there phase 1a's `SET LOCAL` + RLS enforce
isolation unchanged — including over the (now read-only) `run_sql`. The data
layer is untouched; phase 2 is auth + scoping + hardening around it.

## Section 1 — Identity & account linking

- On the first authenticated request, verify `email_verified == true` in the
  token, then link: a single atomic
  `UPDATE users SET external_auth_id = :sub WHERE email = :email AND
  external_auth_id IS NULL RETURNING user_id`. The unique constraint on
  `external_auth_id` makes the first-login race safe; a security event is logged
  when the column is first populated.
- Emails are normalized to lowercase on storage and lookup (case-insensitive
  match). Internationalized/Unicode emails are out of scope for phase 2.
- Subsequent requests resolve by `external_auth_id` (survives email changes).
- **Allowlist** = the `users` table: no matching row → **403**. Clerk's own
  allowlist is an optional second gate at signup.

## Section 2 — Backend verification (`RequestContext` construction)

A FastAPI **dependency** (composes per-route, easy to test), applied to every
non-public route:

1. Extract `Authorization: Bearer <jwt>`. Missing/malformed → **401**.
2. Verify against Clerk JWKS: signature, `iss` (against a hardcoded expected
   value), `exp` (60s clock skew), and audience if configured. Reject
   `alg=none` / alg-confusion. Invalid → **401**.
3. Resolve identity → `users` row (Section 1). No row → **403**.
4. Build `RequestContext` and set the ContextVar; reset in `finally`.
   `session_mode` comes from the conversation row (Section 3), defaulting to
   `individual` for non-conversation routes. **`owner_user_id`/`user_id` come
   only from the verified token, never from the request body.**

**JWKS handling (SSRF + availability):** the JWKS URL comes from
`PENNY_CLERK_JWKS_URL` config — **never derived from the token's `iss`**. Cache
with a ~15-minute TTL and a forced refresh on signature-verification failure
(key rotation). Verify `iss` against `PENNY_CLERK_ISSUER`.

**Auth mode:** `PENNY_AUTH_MODE` defaults to `clerk`. Startup **fails closed**
if the value is neither `clerk` nor `dev`, or if `clerk` mode is missing required
config (`PENNY_CLERK_ISSUER`, `PENNY_CLERK_JWKS_URL`, `PENNY_FRONTEND_ORIGIN`).
In `clerk` mode the phase-1a dev-stub path is **unreachable** — no header
fallback. In `dev` mode the stub accepts **only** an env-pinned principal
(`PENNY_DEV_USER_ID`/`PENNY_DEV_HOUSEHOLD_ID`), never arbitrary `X-Penny-*`
headers, and logs a prominent startup warning.

**CORS:** tighten from `["*"]` to `[PENNY_FRONTEND_ORIGIN,
http://localhost:5173]` with `allow_credentials=True`; scoped methods/headers.
`PENNY_FRONTEND_ORIGIN` is required in clerk mode. Never `*` with credentials.

## Section 3 — Conversation scoping & per-conversation session mode

`conversations` (web schema — a **separate engine/DB**, so phase-1a Postgres RLS
does not automatically cover it) gains `household_id`, `owner_user_id`, and
`session_mode (individual|joint)`, set at creation and immutable.

- **Visibility derives from `session_mode`:** `individual` → owner-only;
  `joint` → household-shared. (One source of truth.)
- **Store filters every read/write** by
  `household_id == ctx.household AND (owner_user_id == ctx.user OR
  session_mode == 'joint')`. `owner_user_id` and `household_id` are stamped from
  the `RequestContext` on creation — never from the client.
- On `/api/chat`, the backend reads the conversation's stored `session_mode` to
  build the turn's `RequestContext`; a request for a conversation the user can't
  access → **404/403**. For a `joint` conversation, `app.current_user` is set to
  the nil sentinel so RLS returns shared-only.
- **Every route is authenticated**, including `GET /api/sessions/{id}` — it does
  an ownership check *before* querying (closes the IDOR). A default-deny routing
  convention: new routes must make a deliberate auth decision.
- **Enforcement is app-layer** for the web schema, with the **same RLS policy as
  a backstop if the web DB is Postgres**. Web-schema isolation is an explicit
  phase-6 audit item regardless.

## Section 4 — Frontend (Clerk + React)

- Wrap the app in `<ClerkProvider>` (`VITE_CLERK_PUBLISHABLE_KEY`). Gate:
  unauthenticated → hosted `<SignIn>` (Google); authenticated → `ChatScreen`
  with a `<UserButton>`/sign-out.
- **Token storage: in-memory only** (not `localStorage`), to limit XSS token
  theft. Audit all rendering of agent/tool output (transaction descriptions,
  merchant names, Amazon data) for proper escaping — no `dangerouslySetInnerHTML`
  with unsanitized content.
- Attach `Authorization: Bearer <getToken()>` per request (fresh each call) on
  the AI SDK `/api/chat` transport and the `/api/sessions/{id}` fetch. Replace
  the `penny:sessionId` localStorage scheme with server-provided, user-scoped
  conversation ids.
- **New-chat mode picker:** Individual | Joint, sent on first message; the
  backend stamps it. The thread list shows the user's individual conversations
  plus the household's joint ones.

## Section 5 — Cron principal (no JWT)

Cron builds an explicit `RequestContext` per job and **fails loudly** if its
principal env is unset (never runs RLS-unscoped). Two job kinds:

- **Per-user individual report:** `ctx = {user, household, individual}`,
  delivered only to that user's verified email.
- **Household shared report:** `ctx = {household, joint/shared-only}`, delivered
  to both users.

**`send_email_report` takes no recipient parameter.** It derives recipients
entirely from the authenticated context: an *individual* context emails that
user; a *joint/household* context emails all household members (from verified
`users.email`). The agent cannot name, add, or influence a recipient — the
injection surface is removed, not merely validated. Cron uses the same
`session_for(ctx)` path as chat, so the same rule applies to scheduled reports.

## Section 6 — `run_sql` read-only

The agent's free-form SQL path (`run_sql`) runs on a **dedicated read-only
Postgres role** (or DML is rejected before execution). RLS already blocks
cross-household reads; making `run_sql` read-only closes the within-household
prompt-injection **write/destruction** path (e.g., a crafted merchant name or
receipt coaxing a `DELETE`/`UPDATE`). Curated `@tool` write functions
(recategorize, verify, persister, conversation persistence) keep a normal
RLS-scoped read-write connection — writes flow only through typed, reviewed code.

---

## UI/UX Requirements

- A signed-out user landing anywhere in the app sees a Google sign-in screen —
  Clerk's hosted `<SignIn>` component wrapped in the app shell — and nothing
  else, so there is one obvious way in.
- After signing in with Google, the user lands in the chat and can see who they
  are signed in as and sign out from a user menu in the header.
- When starting a new chat, the user picks the session mode — **Individual** or
  **Household/Joint** — before their first message, and once a conversation is
  created that mode is fixed and no longer offered.
- A user whose session has expired is re-prompted to sign in rather than shown a
  broken or empty chat, and returns to where they were once re-authenticated.
- The whole authenticated app is wrapped by the shared app shell (header, footer,
  logo), so the chat, the user menu, and the mode picker all sit inside a
  consistent frame across screens.

All new screens use the **shared UI template primitives** (Header, Footer, Logo,
color tokens, type scale, font stack) — no bespoke styling. Screens are
responsive (mobile and desktop) and handle loading, empty, and error states, and
the app shell (header/footer) is consistent across screens.

---

## New dependencies & env

- **Backend:** a JWT/JWKS verification lib (`pyjwt[crypto]` + JWKS fetch/cache,
  or Clerk's SDK). Env: `PENNY_AUTH_MODE` (default `clerk`), `CLERK_SECRET_KEY`,
  `PENNY_CLERK_ISSUER`, `PENNY_CLERK_JWKS_URL`, `PENNY_FRONTEND_ORIGIN`,
  read-only DB role URL (e.g., `PENNY_AGENT_READONLY_DATABASE_URL`), cron
  principal (`PENNY_CRON_*` or reuse `PENNY_DEV_*`). Keep `.env.example` current.
- **Frontend:** `@clerk/clerk-react`. Env: `VITE_CLERK_PUBLISHABLE_KEY`.

## Testing strategy

Postgres-marked where RLS is involved (reuse phase-1a's `@pytest.mark.postgres`).

- **Auth:** 401 on missing/invalid/expired/`alg=none`/wrong-`iss`/wrong-`aud`;
  403 on unknown user and `email_verified=false`.
- **No dev bypass:** in `clerk` mode, `X-Penny-*` headers are ignored (spoof
  attempt gets a real 401/403); startup fails on misconfig / missing CORS origin.
- **Account linking:** first-login link is atomic and idempotent; concurrent
  first requests don't double-link; email match is case-insensitive.
- **IDOR / scoping:** user A cannot read B's conversation (cross-user and
  cross-household → 403/404); individual thread invisible to spouse; joint thread
  visible to household; `owner_user_id` taken from JWT even if the body lies.
- **`run_sql` read-only:** a DML statement via `run_sql` is rejected; a typed
  write tool still succeeds.
- **Email guard:** `send_email_report` exposes **no recipient parameter** —
  recipients derive from the authed context (a per-user report reaches only that
  user; a household report only household members); a prompt attempting to add a
  recipient has no effect because no such parameter exists.
- **CORS:** a disallowed origin is blocked; credentials never combined with `*`.

## Security review outcome

Reviewed by the `rook` agent (2026-07-01). All Critical/High findings are folded
into this design as hard requirements (dev-stub fail-closed & unreachable in
prod; auth on every route incl. `/api/sessions/{id}`; `send_email_report` takes
no recipient parameter (recipients derived from the authed context);
JWKS-from-config + `iss`/`email_verified` checks; `owner_user_id` from
JWT; CORS required; in-memory token storage; cron explicit context;
`run_sql` read-only). No architectural rework was required.

## Amendments to phase 1a (carry when building phase 1a)

Two review findings belong to phase 1a's enforcement and must land there:

- **`WITH CHECK` on every RLS policy** (promote from Task 14 "verify" to a
  required control) so a row cannot be `INSERT`/`UPDATE`-ed into another
  household via `run_sql`.
- **`CHECK (owner_user_id <> '00000000-0000-0000-0000-000000000000')`** on
  financial tables so the joint-session nil sentinel can never coincide with a
  real row; audit the backfill (migration 009) to never write the nil UUID.

## Out of scope (phase 2)

- User creation / signup UI (phase 4) and onboarding (phase 5).
- The participant-set generalization of session mode (see Future work).
- Plaid token **key rotation** procedure (note for a later hardening pass;
  consider a key-version tag on ciphertext).
- Multi-household membership.

## Future work — participant-set session mode

Replace the binary `session_mode` with a `conversation_participant` set: a
conversation is readable by exactly its participants, and its data view is the
intersection of participants' visible accounts under the existing private/shared
model (solo → owner's private + shared; any group → shared-only). This needs no
account ACLs. It generalizes the RLS predicate from a single `current_user`
(+ nil sentinel) to a participants array
(`visibility = 'shared' OR app.participants <@ ARRAY[owner_user_id]`). Deferred
because, without a way to designate an account shared to a *subset* of members,
participant sets add only thread-privacy value, not data-view value — and that
subset-sharing design is the open question to resolve first.
