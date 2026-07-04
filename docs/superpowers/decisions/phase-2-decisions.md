# Phase 2 — Auth / Social Login — Execution Decisions

Ambiguities encountered while executing
`docs/superpowers/plans/2026-07-02-phase-2-auth-social-login.md`, and the
decision taken for each (fail-closed / more-restrictive when security-relevant).

## D1 — Worktree branch base was wrong; re-based onto `feat/account-creation`

The worktree branch (`worktree-agent-a82f152e91d75bafb`) was created from
`origin/main`, not `feat/account-creation`, so it lacked Phase 1a (tenancy,
RLS, RequestContext) and the plan/spec docs, and carried 3 unrelated
"segregate one-off scripts" commits. Local `feat/account-creation` (b66a756)
has Phase 1a + the plan + the spec; the docs-only tip the orchestrator snapshot
reported (490181e) lacks Phase 1a so it could not be the base. **Decision:**
created a fresh branch `feat/phase-2-auth` off local `feat/account-creation`
(b66a756) and did all Phase 2 work there. The 3 one-off-script commits remain on
the original worktree branch (and are already on `main`), so nothing was lost.

## D2 — Web migration number is 019, not the spec's 015

Plan Task 5 and the orchestrator both say **web migration 019** (per the epic
ledger). The spec Section 3 says "migration 015" — but 015 is already taken by
the merged Phase 1a (`015_enable_rls_policies`). **Decision:** used **019**
(spec's 015 is stale; canonical code wins).

## D3 — One shared alembic chain for the 019 web migration (not a second env)

The web store's Postgres deployment reuses the *same* Postgres server as finance
(`resolve_web_url`: for a Postgres finance URL it returns that same URL; the
`web` schema provides separation). The epic ledger numbers finance and web
migrations in one sequence (…017 → 019). **Decision:** added
`019_add_conversation_tenancy.py` to the existing `db/migrations/` chain
(down_revision `017_encrypt_plaid_access_tokens`), keeping a single linear head.
On Postgres it `CREATE SCHEMA IF NOT EXISTS web`, `ALTER`s
`web.conversations` to add the three tenant columns, and enables the
`tenant_isolation` RLS policy (USING + WITH CHECK) + FORCE on
`web.conversations` and `web.conversation_messages`. On SQLite it is a no-op
(dev/tests get the columns from the model via `create_all`). This keeps the web
DB alembic-managed in prod without standing up a second alembic env — simpler,
and matches the single-sequence ledger.

## D4 — conversation_messages RLS scopes via its parent conversation

`conversation_messages` has no tenant columns. Rather than duplicate
`household_id`/`owner_user_id` onto every message row, migration 019's message
policy is `conversation_id IN (SELECT conversation_id FROM web.conversations)`
— which is itself filtered by the conversations policy, so messages inherit the
exact same visibility. One source of truth for the predicate.

## D5 — Task 11 (WITH CHECK + nil-uuid CHECK) is already built in merged Phase 1a

The plan's Task 11 assumes "phase 1a is not yet built" and folds the two
amendments into migrations 010/011. But Phase 1a is merged here and already
ships both controls: `WITH CHECK (<same predicate>)` in
`penny/adapters/db/rls.py` + migration `015`, and
`CHECK (owner_user_id <> nil-uuid)` (`ck_<table>_owner_not_nil`) in migration
`014` + `models.py`. **Decision:** Task 11 becomes verification only. I do NOT
edit the Phase 1a plan `.md` (the orchestrator forbids editing plan/spec docs,
and the control already exists). I add the missing nil-sentinel acceptance test
where the finance acceptance battery lives.

## D6 — Auth settings live in `penny/auth/settings.py`, env documented in `.env.example`

The orchestrator asked to "declare the CLERK_*/PENNY_* env vars in config.py +
.env.example". `config.py` here is the agent-provider `RuntimeConfig`, not a
general env registry; the plan (authoritative) puts auth config in a dedicated
`penny/auth/settings.py` (`AuthSettings`/`load_auth_settings`). **Decision:**
followed the plan — auth settings module is the config surface — and documented
every new `PENNY_*`/`CLERK_*`/`VITE_*` var in `.env.example` (the concrete
env-contract deliverable).
