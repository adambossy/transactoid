# Dev Clerk email re-link (`PENNY_ENV`) — design

## Problem

Local dev is moving to real Clerk auth (keys, network, sign-in step). Clerk
instances have independent user databases, so the developer's identity has a
different subject (`sub`) per instance. The Neon `penny-test` branch is
recreated from prod, whose `users.external_auth_id` values are **prod**-instance
subjects. A local sign-in presents a **dev**-instance subject and misses the
by-subject match in `resolve_or_provision_identity`. The email-idempotent
provision fallback still resolves to the right household (UNIQUE email), but
the subject is never re-stamped — so *every* request takes the slow path,
including a Clerk Backend API identity fetch, and the by-subject fast path
never recovers.

## Decision

1. **Environment identity, not a feature flag.** `config.py` gains the single
   environment reader: `PENNY_ENV` ∈ {`production`, `development`}, anything
   else raises, **default `production`** (fail closed — revised from the
   original default-development decision after review). Local dev opts in via
   `PENNY_ENV=development` in `backend/.env`; deploy also pins production
   explicitly (`deploy/env/deploy.env.template` + `fly.toml`). Future dev-only
   behavior gates on this same var instead of minting new flags.
2. **Verified-email re-link, development only.** In
   `penny/households.py::resolve_or_provision_identity`, precedence becomes:
   1. by `external_auth_id` (unchanged)
   2. claim pending invite — email match, auth id IS NULL (unchanged)
   3. **new, `PENNY_ENV=development` only:** email match, auth id IS NOT
      NULL → re-stamp `external_auth_id` to the incoming subject, log, return
      that household/user
   4. provision solo household (unchanged)

   The call site (`api/auth.py`) already fails closed on unverified email
   before this function runs, so re-link inherits the verified-email guard.

## Edge cases (deliberately minimal — dev-only feature)

- **Prod safety:** default is `development`, so production correctness rests on
  the fly.toml pin; REQUIREMENTS T12 documents this. Cron machines don't serve
  web auth, so their env needs no pin.
- **Two rows sharing an email:** declared out of scope (won't happen);
  `one_or_none()` raises loudly if it ever does.
- **Invite precedence:** re-link sits after invite-claim; predicates are
  disjoint (NULL vs NOT NULL auth id).

## Out of scope

- Frontend changes (dev-principal fallback and the e2e harness stay as-is).
- Deriving Sentry/Langfuse environment tags from `PENNY_ENV` (follow-up).
- The developer's one-time env wiring (Clerk dev-instance keys in the primary
  checkout's `backend/.env` / `frontend/.env`, symlinked into worktrees by the
  WorktreeCreate hook).

## Tests

`backend/tests/test_signup.py`:
- development (default): a row with a different non-NULL subject and matching
  email is re-linked — same household/user returned, subject re-stamped.
- `PENNY_ENV=production`: same setup resolves to the same household via the
  email-idempotent provision path, but the stored subject is never re-stamped
  (today's behavior).
- invalid `PENNY_ENV` raises.
