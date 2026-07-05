# Phase 2b — BYO Keys & Metered Subsidy — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-03
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** Phase 2 (auth — per-user identity). Touches **agent-harness**
(token counting + credential resolver).
**Prerequisite for:** Phase 4 open self-serve signup (the spend cap is the
cost/abuse control open signup needs — closes the phase-4 review gap).

## Goal

Give each new user a small **subsidized token runway** ($2 per user — so a
two-spouse household where both connect gets $4 total, since the grant is
per-user on first Plaid link), and once it's
spent require them to **bring their own credentials** — a provider **API key**
now, or a **subscription** via sanctioned OAuth — which they can also connect at
any time. Credentials are stored server-side, encrypted, per-user, and can never
leak (not to the browser, not to logs, not to the agent's `run_sql`).

## Decisions (locked)

- **Standalone phase (2b)**, depends on Phase 2, **prerequisite for Phase 4**
  open signup.
- **v1 credentials:** provider **API keys** for all supported providers
  (Anthropic, OpenAI, Gemini, …) **plus subscription OAuth only where we can
  register our own client and it is provider-sanctioned.** **Claude Pro/Max
  subscription is deferred and risk-flagged** — its flow requires impersonating
  the Claude Code CLI (fixed client id, `user-agent: claude-cli`, forced system
  block, `claude-code-*` betas), which Anthropic disputes for hosted third-party
  use. Not built in v1.
- **Metering granularity: per model call.** Gate the budget *before* each LLM
  call; accrue exact usage *after* each completion.
- **Subsidy trigger: on Plaid connect** (genuine-intent signal), not on signup.
- **Credentials live in the website/app-owned persistence**, never the finance
  schema — so the agent's `run_sql` cannot reach them (AGENTS.local.md
  agent/website segregation).

## Architecture

Three moving parts:

1. **agent-harness** gains (a) **token counting** — read exact
   `input/output/cache/thinking` tokens from provider responses and compute cost
   from a price table (the mechanism Pi already has), emitted as a usage event;
   and (b) a **credential resolver** hook — the model client for a run is built
   from a caller-supplied `Credential` (the user's key/OAuth token) instead of a
   process-global env key. No ambient/global key fallback on the shared server.
2. **Penny credential store + metering** (website domain) — an encrypted,
   per-user credential store; a usage ledger; a subsidy/spend record; and the
   **gate** (before each model call) that blocks when `spend ≥ subsidy` and no
   BYO credential is connected.
3. **Connect UX** — a settings surface to add/manage credentials, and an
   **in-chat connect prompt** that reuses Phase 5's system-reminder + inline
   generative-UI card (no new nudge mechanism).

## Section 1 — Credential model & secure storage

- **Credential union** (mirrors Pi): `api_key { provider, key }` or
  `oauth { provider, access, refresh, expires }`. One row per
  `(user_id, provider)`.
- **Table `user_credentials`** in the **website persistence** (its own
  `Base`/engine/schema — *not* `penny.adapters.db`), columns: `user_id` (owner),
  `provider`, `kind` (`api_key`|`oauth`), `secret_ciphertext`, `meta` (masked
  hint like `sk-…last4`, expiry for oauth), timestamps. **Owner-scoped RLS**: a
  credential is private to its user — never shared, even within a household.
- **Encryption at rest:** envelope encryption extending the Phase-1a token cipher
  (Fernet/KMS) **with a key-version prefix on the ciphertext** (per the series
  review — cheap rotation later). Decrypt only at the outbound-LLM call site.
- **Never leaves the backend:** the secret is never returned to the client
  (reads expose only the masked hint); all LLM calls run server-side; no
  `dangerouslyAllowBrowser`.
- **Out of `run_sql` blast radius:** the finance schema (what `run_sql` sees) has
  no credential data; credentials are website-owned and separately scoped.
- **Serialized writes + refresh safety:** credential mutations (esp. OAuth
  refresh) go through a single serialized write path under a **DB row/advisory
  lock** (Pi's `modify` contract; OpenClaw's ~180s-stale/120s-timeout pattern),
  because refresh-token **rotation** means a lost write → `invalid_grant`.

## Section 2 — Subscription OAuth (sanctioned only, server-side)

For providers where we can register our **own** OAuth client (not CLI
impersonation):
- **Authorization-Code + PKCE (S256)**, run **server-side**, with a **registered
  HTTPS redirect** on our domain and an **independent CSRF-safe `state`** bound
  to the session (not Pi's `state = verifier` shortcut).
- Token exchange stores `{access, refresh, expires}` encrypted; **refresh under
  the per-(user,provider) lock**, persisting the rotated refresh token
  atomically; refresh proactively (5-min safety skew) before expiry.
- **Claude Pro/Max is explicitly excluded** in v1 (see Decisions).

## Section 3 — Token counting & the credential resolver (agent-harness)

- **Counting:** the harness parses provider `usage` (input/output/cache/thinking
  tokens) per completion and computes `cost_cents` from a model **price table**;
  emits a `ModelUsage` event on the bus (Penny's observability/bridge already
  subscribes to the harness event bus).
- **Resolver:** `Agent`/run accepts a `credential_resolver` (or a resolved
  `Credential`) so the model client is built with the user's key/OAuth token when
  present, else the **platform subsidy key**. Per-request, tenant-keyed; no
  process-global env key is used for a user run on the shared server.
- These are **agent-harness changes** (see Affected plans) — modular, product-
  agnostic, and portable (a "metered BYOK harness" capability).

## Section 4 — Metering, subsidy & the gate (Penny)

- **Ledger `usage_events`** (website domain, owner-scoped): `(user_id, model,
  input/output/cache tokens, cost_cents, ts)`, one row per completion, written
  from the harness usage event.
- **`user_billing`** (owner-scoped): `subsidy_granted_cents`, and `spend_cents`
  (or derived by summing the ledger). **Subsidy granted on first Plaid link**
  (configurable amount via `PENNY_SUBSIDY_CENTS`, default 200 = $2/user).
- **The gate** runs in Penny's agent-invocation path **before each model call**:
  if the user has a connected BYO credential → use it (their provider bills them;
  no subsidy accounting). Else compute `remaining = subsidy_granted - spend`; if
  `remaining ≤ 0` → **block the turn** and enqueue the connect prompt; otherwise
  proceed on the platform key and accrue after the completion.
- **Model pricing** is config (single source of truth) — a `PENNY_MODEL_PRICES`
  table (input/output/cache $/Mtok per model), used by the harness cost calc and
  kept in `config.py`.

## Section 5 — Connect UX (reuses Phase 5)

- **In-chat prompt:** when the subsidy is low/exhausted, Penny enqueues a
  `kind="byo_credential"` **system reminder** (Phase 5 mechanism) so the agent
  nudges naturally, and renders an **inline generative-UI "Connect a provider"
  card** (Phase 5 tool-renderer pattern) with the key form / OAuth buttons.
- **Settings surface:** a "Providers & billing" screen to add an API key
  (entered once, masked thereafter), connect/disconnect OAuth, and see **credits
  remaining** + current provider.

## UI/UX Requirements

- As a new user, I get a few dollars of free usage after connecting my bank, and
  I'm clearly told how much runway I have left.
- When my free runway runs out, Penny tells me in-chat and lets me connect my own
  key or subscription right there, without leaving the conversation.
- I can add, see (masked), or remove my provider credentials from a settings
  screen at any time, and I trust they're stored securely and never shown in full
  again.
- I never see another user's credentials or usage, and my key is never exposed in
  the page or a URL.

All new screens use the shared UI template primitives (Header, Footer, Logo,
color tokens, type scale, font stack) — no bespoke styling — responsive, with
loading, empty, and error states, and a consistent app shell.

## Browser E2E validation (Playwright)

Reusing the phase-1a harness + `signInAsTestUser`:
- Connect an API key in settings → it's accepted, shows only a masked hint on
  reload, and is never present in the DOM/network response body.
- Drive usage until the (test-lowered) subsidy is exhausted → the next turn is
  gated with the in-chat connect card; connecting a key unblocks the next turn.
- A second user never sees the first user's credentials, usage, or remaining
  credits (cross-user isolation via the UI).

## Security (bake-in for Phase 6)

Adds a **"BYO credential" dimension** to the Phase-6 coverage matrix:
- Encryption at rest (key-version prefix), decrypt only at call site, never to
  browser/logs/traces (scrub token-exchange error strings), masked reads.
- Credentials unreachable by the agent's `run_sql` (website schema, owner-scoped
  RLS) — an explicit cross-tenant + cross-domain leakage test.
- OAuth: independent `state`, PKCE, registered redirect, refresh-rotation atomic
  under lock; no CLI-impersonation surface shipped.
- No ambient/global key fallback for a user run; the gate cannot be bypassed by a
  client-supplied model/credential parameter.

## Affected plans (to update)

- **agent-harness** (own repo): add token counting (usage → cost) + the
  credential-resolver hook. New harness capability; version-pin for prod
  (ties to the series-review three-repo pinning item).
- **Phase 4 (signup):** open self-serve signup **depends on this phase's spend
  cap**; the phase-4 abuse/cost item is largely resolved here. Add the dependency
  edge; the subsidy gate is the per-user cost control.
- **Phase 5 (onboarding):** add a `byo_credential` onboarding/reminder item + the
  connect card renderer (reuses the reminder + generative-UI mechanism).
- **Phase 6 (audit):** add the BYO-credential coverage dimension above.
- **Phase 2 (auth):** credentials/usage key off the verified user — no change
  beyond consuming `RequestContext`.
- **Config:** `PENNY_MODEL_PRICES`, `PENNY_SUBSIDY_CENTS`, provider OAuth client
  ids/secrets, and the platform subsidy provider key(s) — all `PENNY_*` env.

## Modularization

The credential store + metering + gate is a portable **"metered BYOK"** module:
an encrypted per-tenant credential vault, a usage ledger keyed to provider
`usage`, and a pre-dispatch budget gate — reusable by any hosted multi-tenant
agent product. Keep provider specifics (price table, OAuth client config) behind
config; keep Penny's subsidy policy (grant-on-Plaid) separate from the generic
gate.

## Out of scope

- **Claude Pro/Max subscription** auth (deferred, risk-flagged — needs a ToS
  decision + our own sanctioned path).
- Paid credit top-ups / Stripe / prepaid wallet (future — this phase is
  subsidy-then-BYOK, not billing).
- Team/household-shared credential pools (credentials are per-user in v1).

## Future work

- Claude Pro/Max subscription behind an explicit risk-accepted toggle if/when a
  sanctioned path exists.
- Paid top-ups (Stripe) as an alternative to BYOK.
- Per-household shared credit pool / org billing.
