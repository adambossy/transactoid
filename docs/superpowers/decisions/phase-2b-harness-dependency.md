# Phase 2b — agent-harness dependency: BUILT (integration contract)

The agent-harness half of Phase 2b (plan Tasks 1 & 2 — token counting + per-run
credential resolver) is **already built and verified** on a branch. When the 2b
Penny work runs, it consumes this; **do not rebuild it.**

## Where it lives
- Repo: `~/code/agent-harness` (Penny's editable dep).
- Worktree: `~/code/agent-harness-2b`, branch `feat/usage-credential-resolver`,
  HEAD `8c8de30`.
- Commits: `fa13834` usage/ModelUsage, `8c8de30` credential resolver.
- Verified: `uv run pytest -q` → 724 passed, 2 skipped (pre-existing pgvector).
  New: 6 usage tests + 13 credential tests. New modules are ruff/mypy clean.
- **NOT merged into agent-harness `main`** on purpose — see the breaking change
  below. Integrate it as part of executing Phase 2b, not before.

## Public API to consume (from `agent_harness.core` / `agent_harness`)
- Credentials (`agent_harness/core/credentials.py`):
  - `ApiKeyCredential(provider, key)`, `OAuthCredential(provider, access_token,
    refresh_token=None, expires_at=None)` — frozen; `Credential = ApiKeyCredential
    | OAuthCredential`; `CredentialResolver = Callable[[], Credential]`.
  - `resolve_credential(*, credential=None, credential_resolver=None) -> Credential`
    (precedence credential → resolver() → raise `NoCredentialError`).
  - `api_key_from_credential(credential, *, expected_provider) -> str`
    (provider mismatch → `ConfigError`; OAuth → `NotSupportedError`).
  - `NoCredentialError(ConfigError)` in `agent_harness/core/errors.py`.
- `Agent.__init__` new kwargs (all default `None`, backward-compatible):
  `credential`, `credential_resolver`, `usage_pricer`.
- Usage/cost (`agent_harness/usage/counting.py`, injected — core stays pure):
  `ModelPrice(...)`, `PriceTable(prices)`, `compute_cost(usage, price) -> Cost`,
  `price_table_pricer(price_table) -> UsagePricer`. Event `ModelUsage(model_name,
  usage, cost)` on the bus.
- Providers (`Anthropic|OpenAI|Google`) `__init__` gained `credential` /
  `credential_resolver` + a `use_credential(credential)` method.

## Two integration facts the 2b Penny work MUST honor
1. **Breaking: the global env-key fallback is GONE.** Providers no longer read
   `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`GOOGLE_API_KEY`. Penny's
   `agent_factory.py` (and chat/cron paths) that today rely on the env key MUST
   pass a key explicitly — for 2b, via the per-request `Agent(credential=...)` /
   `credential_resolver=...` that the pre-dispatch gate supplies. Until this is
   wired, pulling the harness branch will break Penny's current chat path. This
   is why the harness branch is not merged into `main` yet.
2. **Provider mutation ⇒ construct the Agent per request.** `Agent` resolves the
   credential at the start of each run and pushes it into the (shared) provider
   via `use_credential`, which rebuilds the client. Concurrent runs of *one*
   `Agent` with *different* per-run credentials would race. Penny already builds
   an agent per request, so this is fine — but keep it per-request; don't share
   one `Agent` across users.

## Cost consumption (subsidy metering)
To meter, pass `Agent(usage_pricer=price_table_pricer(PriceTable(<Penny prices>)))`
and subscribe a `ModelUsage` handler that writes the usage ledger (2b Task 5).
`OTELSubscriber` needs no change. Prices are per-million-tokens; Penny owns the
price table via `PENNY_MODEL_PRICES`.
