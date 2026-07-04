# Phase 2b — execution decisions (ambiguity log)

This file records ambiguities encountered while executing the Phase 2b plan and
the decision taken for each. Security/billing-sensitive → when ambiguous, the
more restrictive / fail-closed option was chosen. This doc is owned by the 2b
execution agent alone (the plan/spec/harness-dependency docs are not edited).

## D0 — Worktree base was stale; fast-forwarded to `feat/account-creation`
The isolated worktree started 95 commits behind `feat/account-creation` (its
HEAD was an ancestor on the main lineage, missing Phases 0/1a/1b/2 and the plan
docs). Fast-forwarded the worktree branch to `feat/account-creation` with
`git merge --ff-only` (non-destructive; the tree was clean and HEAD was an
ancestor). No other worktree touched.

## D1 — The harness "breaking change" does NOT break Penny's current tests
The plan/decision doc warn that removing the global env-key fallback breaks
Penny's chat/cron path. In this codebase it does not: `agent_factory.build_model()`
already reads `GOOGLE_API_KEY` itself and passes it **explicitly** as
`GoogleProvider(api_key=...)`, and `GoogleProvider` still accepts an explicit
`api_key=` (only the *env fallback inside the provider* was removed). The
baseline gate was fully green (301 passed) before any change. The real work is
therefore (a) exercising the credential seam so the per-user gate can supply a
per-run key, and (b) bumping the prod git pin. See D2/D3.

## D2 — Build the model PER REQUEST (not the cached module-level singleton)
`api/main._get_model()` cached one `GeminiModel`/`GoogleProvider` for the whole
process. The harness resolves a run's credential by **mutating the shared
provider** via `use_credential` (rebuilds its client). A cached, shared provider
mutated per-request would race across concurrent users (the harness-dependency
doc's explicit warning). Decision: the gate builds a fresh model per request via
`agent_factory.build_model(credential=...)`, so each request owns its provider
and the per-user credential can be applied safely. The dev/default path
(`build_model()` with no arg) still reads the platform key from env and passes it
as an explicit `ApiKeyCredential(provider="google", ...)`.

## D3 — Active provider is "google" (Gemini); BYO keys are matched to it
Penny's runtime model is Gemini-only (`GoogleProvider`, name `"google"`,
`gemini-3.5-flash`). The vault stores credentials for any provider string, but
the **gate** selects a BYO credential only for the active provider (`"google"`).
A stored credential for a different provider (e.g. an OpenAI key) is not usable
by the current single-model runtime, so the gate treats "no google BYO cred" as
no-BYO and falls through to subsidy/blocked. Multi-provider model selection is
future work.

## D4 — Billing data is OWNER-private even in joint sessions → its own GUC usage
Conversation RLS keys on `app.current_user` = `effective_user_id(ctx)`, which is
the **nil sentinel** in a joint session (shared-only). Credentials/usage/billing
are private to the real user regardless of session mode (plan: "owner-scoped,
not household; no shared arm"). So the billing web-session sets
`app.current_user` to the **real** `ctx.user_id` (never the nil sentinel) and the
billing RLS predicate is purely `user_id = current_setting('app.current_user')`.
Billing uses its own web session (separate transaction from the conversation
store), so there is no GUC conflict. On SQLite dev the store filters every query
by `user_id == ctx.user_id` (the only tenant layer there).

## D5 — Billing tables live on the existing website `WebBase`/`web` schema
Rather than standing up a third `Base`/engine, the billing models register on the
existing website `WebBase` (`penny.api.persistence.models`) and land in the same
`web` schema / `penny_web.db` file — already segregated from finance and out of
`run_sql`'s blast radius. `create_web_schema()` (`WebBase.metadata.create_all`)
creates them; migrations 020/021 (Postgres-guarded) add owner-scoped RLS, exactly
mirroring how 019 layered RLS onto the create_all-managed web conversation tables.

## D6 — Credential secrets share the platform at-rest key (PENNY_PLAID_TOKEN_KEY)
The plan says "extend the phase-1a token cipher". `token_cipher.py` gains generic
`encrypt_secret`/`decrypt_secret` using the same versioned-envelope (`v1:` prefix)
and the same Fernet key env var (`PENNY_PLAID_TOKEN_KEY`) — one at-rest key for
all platform secrets. A dedicated `PENNY_CREDENTIAL_KEY` can be split out later
via the key-version mechanism without a re-encrypt migration.

## D7 — Subsidy-on-Plaid-link grant seam is website-owned; wiring deferred to phase 5
The subsidy grant must run in the **website** domain (it writes the web billing
DB). Today's Plaid connect is the **agent tool** `connect_new_account`, which may
not import website billing (agent→website is a forbidden dependency). The grant
itself (`metering.grant_subsidy`, idempotent) and its policy wrapper
(`gate.grant_subsidy_on_plaid_link`) are implemented and unit-tested; the actual
call site belongs to phase 5's **website-owned** Plaid exchange route/card, which
does not exist yet. Deferred as a phase-5-reuse follow-up (does not block the
billing core).

## D8 — Phase-5 reminder subsystem absent → minimal standalone connect-prompt
Phase 5 (reminder subsystem, `onboarding.py`, generative-UI tool-renderer) is not
built. Per the orchestrator instruction, Task 9 implements a minimal standalone
connect-prompt (the `connect_provider` `@tool` returning structured provider
options + a lightweight in-memory reminder record) instead of reusing phase-5
machinery. Reuse of the phase-5 reminder/card is a follow-up. The Blocked chat
turn also streams a self-contained friendly connect message directly (no phase-5
card needed to deliver the prompt to the user).

## D9 — OAuth pending-state store is process-local (server-side)
The CSRF `state → {user, provider, code_verifier}` map is a process-local dict
with a TTL — server-side and correct for a single machine, but not shared across
processes. A multi-process/multi-machine deploy needs a shared store (Redis/DB).
Deferred: no provider is actually registered in v1 (Claude Pro/Max excluded), so
the OAuth flow is a tested scaffold, not a live path. The token exchange is
injectable (`TokenExchanger`) so tests fake the provider; the default uses stdlib
`urllib` (no new dependency) and scrubs errors.

## D10 — Billing UI is implemented but not compiled/Playwright-verified here
`frontend/` has no `node_modules` in this environment, so `ProvidersBillingScreen`
/ `ConnectProviderCard` and the Playwright spec were written to match the existing
frontend patterns (`ChatScreen` getToken/authHeaders, `@penny/ui` primitives) but
not type-checked or run. The subsidy-exhaustion and cross-user E2E arms are gated
behind `PENNY_E2E_BILLING` / `PENNY_E2E_CLERK`; only the connect-and-mask arm runs
on the default dev-principal harness. Registering `ConnectProviderCard` with a
real in-chat tool-renderer is a phase-5-reuse follow-up (the component is ready).

## D11 — Task 12 cross-plan edits: canonical REQUIREMENTS.txt only
The orchestrator forbids editing plan/spec/decision `.md` files. Task 12's
intent — record phase-2b in the cross-plan docs + the phase-6 audit matrix — is
satisfied on the **canonical** side by updating `REQUIREMENTS.txt` (new P9 "BYO
keys & metered subsidy" + T11 "Credential security & no-ambient-key gate"). The
edits to the non-canonical phase-4/5/6 plan/spec `.md` and the epic index are
intentionally **deferred** (not made) to respect that instruction; the BYO
security dimension for the phase-6 coverage matrix is captured in T11 instead.

## Harness dependency integration
Bumped `backend/pyproject.toml`'s prod agent-harness git pin from the pre-2b ref
to merged main `f32b2403b0a250179fa7fe5f33a4fa8508e6cef6` (the editable
`[tool.uv.sources]` path already resolved to local main, which is why the
baseline suite was green before any change). No harness code was modified.
