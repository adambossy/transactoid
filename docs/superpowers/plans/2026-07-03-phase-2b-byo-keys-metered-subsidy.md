# Phase 2b — BYO Keys & Metered Subsidy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 2b design](../specs/2026-07-03-phase-2b-byo-keys-metered-subsidy-design.md).
> **Depends on:** Phase 2 (auth / `RequestContext`, web-DB RLS plumbing). **Prerequisite for:** Phase 4 open signup.

**Goal:** Give each user a small subsidized token runway; once spent, require a
BYO provider API key (or sanctioned OAuth). Credentials are per-user, encrypted,
website-owned, and unreachable by the agent's `run_sql`. Metering gates each
model call.

**Architecture:** agent-harness gains token counting (usage→cost event) + a
per-run credential resolver (no global key fallback). Penny adds a web-DB
credential vault + usage ledger + billing + a pre-dispatch gate, and reuses
Phase 5's reminder + generative-UI card for the connect prompt.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 + Alembic (web chain), the phase-1a
token cipher (key-version envelope), agent-harness (own repo, editable dep),
React 19 + phase-5 tool-renderer, phase-0 `@penny/ui`.

## Global Constraints

- **Verification gate:** from `backend/`: `uv run ruff check .` ·
  `uv run ruff format --check .` · `uv run pytest -q`. agent-harness tasks run
  that repo's own gate.
- **Migrations (ledger):** web DB — **`020_add_user_credentials`**,
  **`021_add_usage_events_and_user_billing`** (web chain head after phase-2
  `019`). Owner-scoped `tenant_isolation` RLS (USING + WITH CHECK); web store
  binds `SET LOCAL` (phase-2 plumbing).
- **Secrets never leave the backend:** decrypt only at the outbound-LLM call
  site; reads expose only a masked hint; no `dangerouslyAllowBrowser`; scrub
  token-exchange error strings before logging.
- **No ambient/global key for a user run** on the shared server; the gate cannot
  be bypassed by a client-supplied model/credential parameter.
- **Owner-scoped, not household:** credentials/usage are private to the user even
  within a household (RLS keys on `owner_user_id == ctx.user`, no shared arm).
- New env (`PENNY_*`): `PENNY_MODEL_PRICES` (JSON price table),
  `PENNY_SUBSIDY_CENTS` (default 500), `PENNY_SUBSIDY_PROVIDER_KEY` (platform
  key), provider OAuth client ids/secrets.

## File structure

- agent-harness — `agent_harness/usage/counting.py` (usage→cost, `ModelUsage`
  event), `agent_harness/credentials.py` (`Credential`, resolver hook); modify
  the model-client build path + `Agent` to accept `credential`/resolver.
- Penny — `backend/penny/billing/` (`vault.py`, `metering.py`, `gate.py`,
  `oauth.py`, `prices.py`); web models `UserCredential`, `UsageEvent`,
  `UserBilling`; migrations 020/021; `backend/penny/tools/connect_provider.py`;
  modify `agent_factory`/chat path (gate + resolver wiring), `config.py`.
- Frontend — `frontend/src/ProvidersBillingScreen.tsx`,
  `frontend/src/ConnectProviderCard.tsx` (phase-5 renderer registration).

---

### Task 1 (agent-harness): token counting → `ModelUsage` event

**Files:** create `agent_harness/usage/counting.py`; modify the model-response
handling to emit the event; test `tests/usage/test_counting.py`.

**Interfaces:**
- `@dataclass(frozen=True) ModelUsage(model: str, input_tokens: int,
  output_tokens: int, cache_read_tokens: int, cache_write_tokens: int,
  thinking_tokens: int, cost_cents: float)`.
- `compute_cost_cents(model: str, usage: dict, prices: PriceTable) -> float` —
  from a `PriceTable` (`{model: {input, output, cache_read, cache_write} $/Mtok}`).
- The loop emits `ModelUsage` on the event bus after each completion, parsed from
  the provider `usage` block (Anthropic/OpenAI/Gemini shapes).

- [ ] Step 1: failing test — `compute_cost_cents("claude-x", {input:1_000_000,
  output:0,...}, {"claude-x":{"input":300,...}})` returns `300.0`; unknown model
  raises. Step 2: run, fail. Step 3: implement pure `compute_cost_cents` + the
  `ModelUsage` dataclass + bus emission in the completion path. Step 4: pass.
  Step 5: commit `feat(usage): token counting + ModelUsage cost event`.

---

### Task 2 (agent-harness): per-run credential resolver

**Files:** create `agent_harness/credentials.py`; modify the model-client
factory + `Agent` init; test `tests/test_credential_resolver.py`.

**Interfaces:**
- `Credential = ApiKeyCredential{provider, key} | OAuthCredential{provider,
  access_token, ...}` (discriminated union).
- `Agent(..., credential: Credential | None = None,
  credential_resolver: Callable[[], Credential] | None = None)`. The model client
  for a run is built from the resolved `Credential`; **if neither is supplied and
  no explicit platform key is passed, raise** (no silent global-env fallback).
- A `resolve_credential()` helper the host implements (Penny's gate provides it).

- [ ] TDD: a run built with an `ApiKeyCredential` uses that key (assert via a fake
  client capturing the key); a run with neither credential nor explicit key
  raises `NoCredentialError`. Commit `feat(credentials): per-run credential
  resolver, no global-key fallback`.

---

### Task 3 (Penny): `user_credentials` vault + migration 020 + encryption

**Files:** web model `UserCredential`; `backend/penny/billing/vault.py`;
`backend/db/migrations/web/020_add_user_credentials.py`; test
`backend/tests/billing/test_vault.py`.

**Interfaces:**
- `UserCredential` (web `Base`): `id`, `user_id` (owner), `provider`, `kind`
  (`api_key`|`oauth`), `secret_ciphertext`, `meta` (JSON: masked hint / expiry),
  `created_at`/`updated_at`; unique `(user_id, provider)`; owner-scoped RLS.
- Encryption via **key-version envelope** extending phase-1a `token_cipher`
  (`encrypt_secret`/`decrypt_secret`, `v1:` prefix).
- `vault.upsert_api_key(session, ctx, *, provider, key)` — encrypt, store masked
  hint `sk-…{last4}`, single serialized write (row lock via
  `with_for_update()` / `SELECT … FOR UPDATE` on the `(user, provider)` row).
- `vault.get_credential(session, ctx, *, provider) -> Credential | None` —
  decrypts (backend only). `vault.masked(session, ctx) -> list[dict]` — hint only,
  **never** the secret. `vault.remove(session, ctx, *, provider)`.

- [ ] TDD (SQLite + Postgres-marked for RLS): upsert then `masked()` returns only
  the hint (never the key); `get_credential` round-trips the key; a second user
  can't read the first's credential (RLS, raw SQL). Commit `feat(billing):
  encrypted per-user credential vault (migration 020)`.

---

### Task 4 (Penny): `usage_events` + `user_billing` + migration 021

**Files:** web models `UsageEvent`, `UserBilling`;
`backend/db/migrations/web/021_add_usage_events_and_user_billing.py`; test
`backend/tests/billing/test_metering.py`.

**Interfaces:**
- `UsageEvent` (web, owner-scoped RLS): `(id, user_id, model, input_tokens,
  output_tokens, cache_tokens, cost_cents, created_at)`.
- `UserBilling` (web, owner-scoped): `(user_id PK, subsidy_granted_cents,
  created_at, updated_at)`; `spend_cents` derived by summing the ledger (or a
  denormalized running total updated in the same txn).
- `metering.record_usage(session, ctx, usage: ModelUsage)` — inserts a
  `UsageEvent`. `metering.remaining_cents(session, ctx) -> int` —
  `subsidy_granted - sum(cost_cents)`. `metering.grant_subsidy(session, ctx, *,
  cents)` — idempotent (once per user).

- [ ] TDD: record two usages → `remaining_cents` decreases exactly; `grant_subsidy`
  is idempotent; RLS isolates per user (Postgres). Commit `feat(billing): usage
  ledger + subsidy record (migration 021)`.

---

### Task 5 (Penny): usage subscriber (harness event → ledger)

**Files:** modify the bridge/observability bus subscription; test
`backend/tests/billing/test_usage_subscriber.py`.

**Interfaces:** a bus subscriber that, on each `ModelUsage` event during a run,
calls `metering.record_usage(session_for(ctx), ctx, usage)`. Keyed to the run's
`RequestContext`.

- [ ] TDD: a fake run emitting two `ModelUsage` events writes two `UsageEvent`
  rows for the ctx user. Commit `feat(billing): subscribe harness usage events to
  the ledger`.

---

### Task 6 (Penny): the gate + subsidy-on-Plaid-link

**Files:** `backend/penny/billing/gate.py`; modify the chat agent-invocation path
+ the phase-5 Plaid exchange; test `backend/tests/billing/test_gate.py`.

**Interfaces:**
- `gate.resolve_for_run(session, ctx) -> GateDecision` where `GateDecision` is
  either `UseByo(credential)` (a connected BYO cred → build the model client with
  it; no subsidy accounting), `UseSubsidy(platform_key)` (remaining > 0 → platform
  key, accrue after), or `Blocked(reason)` (remaining ≤ 0 and no BYO).
- The chat path calls `gate.resolve_for_run` **before** building the agent: on
  `Blocked`, it does **not** run the model — it enqueues the `byo_credential`
  reminder (Task 9) and returns a friendly "runway exhausted, connect a provider"
  turn; on `UseByo`/`UseSubsidy` it passes the credential/key to the harness
  resolver (Task 2).
- **Subsidy grant on first Plaid link:** the phase-5 `exchange_public_token`
  additionally calls `metering.grant_subsidy(ctx, cents=PENNY_SUBSIDY_CENTS)`
  (idempotent) — genuine-intent trigger, not signup.

- [ ] TDD: remaining>0 & no BYO → `UseSubsidy`; remaining≤0 & no BYO → `Blocked`;
  BYO present → `UseByo` regardless of remaining. First Plaid exchange grants the
  subsidy once. Commit `feat(billing): pre-dispatch gate + subsidy-on-plaid-link`.

---

### Task 7 (Penny): sanctioned OAuth (auth-code + PKCE, server-side)

**Files:** `backend/penny/billing/oauth.py`; API routes `GET
/api/providers/{provider}/oauth/start`, `GET /api/providers/{provider}/oauth/
callback`; test `backend/tests/billing/test_oauth.py`.

**Interfaces:**
- `oauth.start(session, ctx, *, provider) -> {authorize_url}` — PKCE S256, an
  **independent CSRF-safe `state`** bound to the session (stored server-side),
  registered HTTPS redirect on our domain.
- `oauth.callback(session, ctx, *, provider, code, state)` — verify `state`,
  exchange code→`{access, refresh, expires}`, store encrypted via the vault
  (`kind='oauth'`), **refresh under the per-(user,provider) row lock**, persisting
  the rotated refresh token atomically; proactive refresh 5-min before expiry.
- **Claude Pro/Max excluded** — only providers where we register our own client.

- [ ] TDD (faked provider): start returns a URL with a distinct `state` and
  `code_challenge`; callback with a mismatched `state` is rejected; a valid
  callback stores an oauth credential; a refresh rotates and persists the new
  refresh token atomically. Commit `feat(billing): sanctioned server-side OAuth
  (PKCE, CSRF state, locked refresh)`.

---

### Task 8 (Penny): config — prices, subsidy, `/api/me/billing`

**Files:** `backend/penny/billing/prices.py`, `config.py`; route `GET
/api/me/billing`; `.env.example`; test `backend/tests/billing/test_billing_api.py`.

**Interfaces:** `load_price_table()` from `PENNY_MODEL_PRICES`; `GET
/api/me/billing` → `{remaining_cents, subsidy_granted_cents, provider:
"subsidy"|<byo provider>, credentials: [masked...]}` (never secrets). `.env.example`
documents `PENNY_MODEL_PRICES`, `PENNY_SUBSIDY_CENTS`,
`PENNY_SUBSIDY_PROVIDER_KEY`, OAuth client ids.

- [ ] TDD: `/api/me/billing` returns remaining + masked credentials, no secret in
  the body. Commit `feat(billing): model prices config + /api/me/billing`.

---

### Task 9 (Penny): `byo_credential` reminder + connect tool

**Files:** modify `backend/penny/onboarding.py` (add `byo_credential` item/kind)
or the reminder producer; create `backend/penny/tools/connect_provider.py`; test
`backend/tests/billing/test_connect_prompt.py`.

**Interfaces:** reuses the **Phase 5** reminder subsystem — enqueue a
`kind="byo_credential"` reminder when the gate blocks (or runway is low). A
`connect_provider` `@tool` returns structured content (`{providers, oauth_urls}`)
for the inline card (Task 10). No new nudge/queue plumbing (per phase-5's "keep
extensible to a new kind + card").

- [ ] TDD: a blocked gate enqueues exactly one `byo_credential` reminder
  (override); the tool returns provider options. Commit `feat(billing): in-chat
  connect-a-provider reminder + tool`.

---

### Task 10 (Frontend): Providers & billing screen + inline connect card

**Files:** create `frontend/src/ProvidersBillingScreen.tsx`,
`frontend/src/ConnectProviderCard.tsx`; register the renderer in `main.tsx`.

**Interfaces:** the settings screen (uses `@penny/ui` primitives) shows credits
remaining + current provider, an API-key form (entered once, masked thereafter),
and connect/disconnect OAuth buttons — all via the authed fetch. The
`ConnectProviderCard` is registered with the Phase-5 tool-renderer for
`connect_provider`, rendering inline in chat with the key form / OAuth buttons;
on success it posts to the vault route and the next turn unblocks. **The key is
never rendered back** (masked hint only).

- [ ] Manual + Playwright verification (Task 11). Commit `feat(frontend):
  providers/billing screen + inline connect-provider card`.

---

### Task 11: Playwright E2E + Postgres RLS suite

**Files:** `frontend/e2e/byo-credential.spec.ts`;
`backend/tests/billing/test_billing_rls.py` (Postgres-marked).

- [ ] **E2E** (reuse phase-1a harness + `signInAsTestUser`): (a) connect an API
  key in settings → masked on reload, **not present in the DOM or the network
  response body**; (b) with a test-lowered subsidy, drive usage until exhausted →
  next turn gated with the inline connect card; connecting a key unblocks the
  next turn; (c) a second user never sees the first's credentials/usage/credits.
- [ ] **RLS suite** (Postgres): `user_credentials`/`usage_events`/`user_billing`
  are owner-scoped — user A's raw `SELECT` returns zero of B's rows; a WITH-CHECK
  write into another user is rejected.
- [ ] Commit `test(billing): BYO-credential E2E + owner-scoped RLS suite`.

---

### Task 12: cross-plan updates (dependencies + audit dimension)

**Files:** edit the phase-4 plan (dependency + abuse item resolved-by-2b),
phase-5 plan (note the `byo_credential` kind reuses its mechanism — already
noted), phase-6 spec/plan (add the **BYO-credential coverage dimension** from the
spec's Security section), and the epic index (2b→4 edge already present).

- [ ] Apply the edits; confirm the phase-6 coverage matrix lists the BYO
  dimension (encryption/masked reads/no-run_sql-reach/OAuth safety/no-ambient-key).
  Commit `docs: wire phase-2b into phases 4/5/6 (deps + audit dimension)`.

---

## Self-Review

**Spec coverage:** credential model + secure storage → Task 3; subscription OAuth
→ Task 7; token counting + resolver (agent-harness) → Tasks 1–2; metering/subsidy/
gate → Tasks 4–6; connect UX → Tasks 9–10; config → Task 8; security bake-in +
RLS → Tasks 3/11 + Task 12 (phase-6 dimension); affected-plans updates → Task 12.
UI/UX + E2E → Tasks 10–11.

**Placeholder scan:** tasks compress the TDD rhythm to one line each (this is a
later-phase plan; the pattern is established in phases 1a/2). Core interfaces and
security invariants are concrete. No TBD.

**Type consistency:** `ModelUsage`, `Credential`/`ApiKeyCredential`/
`OAuthCredential`, `GateDecision`(`UseByo`/`UseSubsidy`/`Blocked`), `vault.*`,
`metering.*`, `gate.resolve_for_run` are used consistently; reuses phase-1a
cipher, phase-2 web-RLS + `RequestContext`, phase-5 reminder + tool-renderer.

## Modularization

Per the spec: the vault + metering + gate is a portable **"metered BYOK"** module
(encrypted per-tenant credential vault + usage ledger + pre-dispatch budget gate),
with provider price table / OAuth config behind config and Penny's grant-on-Plaid
subsidy policy kept separate from the generic gate. The harness token-counting +
resolver is a product-agnostic harness capability.

## Execution Handoff

Execute after Phase 2 (auth, web-RLS) and alongside/after Phase 5 (reuses its
reminder + card). agent-harness tasks (1–2) land in that repo. Postgres tasks need
`POSTGRES_TEST_URL`. Subagent-driven recommended.
