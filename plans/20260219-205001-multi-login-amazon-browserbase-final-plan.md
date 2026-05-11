# Final Plan: Multi-Login Amazon Scraping with DB Profiles, Sequential Auth, Parallel Scrape, and Strong Agent Tool Contracts

## Summary
Implement a full multi-login Amazon scraping system that:
1. Stores configured Amazon logins in DB (not env-only, not singleton state).
2. Shows login/auth steps only for configured profiles that are missing/invalid auth.
3. Runs first-time/reauth flows **sequentially** (profile by profile).
4. Runs scraping for ready profiles **in parallel**.
5. Retries each failed profile once.
6. Persists deduped union of orders/items across profiles.
7. Exposes login management as **multiple dedicated agent tools** (not one overloaded tool), matching CLI capabilities.
8. Removes `AmazonScraperStateDB` and its unrun migration entirely.

This consolidates all requirements from the recent feedback.

## Goals and Success Criteria

### Product goals
- Support one or more Amazon login profiles.
- Avoid repeated login for profiles with active context.
- Detect stale/invalid context and require re-login for that specific profile.
- Keep user flow predictable: auth prompts in sequence, scraping in parallel.

### Success criteria
- A run with N enabled profiles only opens login flow for profiles that need auth.
- Profiles with active valid context skip login.
- Profiles with stale context trigger reauth.
- Scrape completes with `success`/`partial`/`error` plus per-profile details.
- CLI and agent can both manage profile configuration with strict contracts.
- No runtime references to `amazon_scraper_state`.

## Scope

### In scope
- New DB model/migration for multi-profile login config.
- Remove singleton Amazon scraper state model/migration.
- Orchestrator flow redesign for sequential auth + parallel scrape.
- Profile-level retry and result aggregation.
- Dedicated agent tools for profile management.
- CLI command parity with those tools.
- Tests and logging.

### Out of scope
- Encryption/key management changes for stored context IDs.
- UI redesign beyond presenter output updates.

## Data Model and Migration Plan

## 1) Remove singleton state
- Delete model `AmazonScraperStateDB` from `src/transactoid/adapters/db/models.py`.
- Remove related facade methods from `src/transactoid/adapters/db/facade.py`:
  - `get_amazon_browserbase_context_id`
  - `set_amazon_browserbase_context_id`
- Delete migration `db/migrations/009_add_amazon_scraper_state.py` (confirmed never run).
- Remove tests tied to singleton state.

## 2) Add profile table
Create `amazon_login_profiles` with:
- `profile_id` INTEGER PK AUTOINCREMENT
- `profile_key` TEXT UNIQUE NOT NULL
- `display_name` TEXT NOT NULL
- `browserbase_context_id` TEXT NULL
- `enabled` BOOLEAN NOT NULL DEFAULT TRUE
- `sort_order` INTEGER NOT NULL DEFAULT 0
- `last_auth_at` TIMESTAMP NULL
- `last_auth_status` TEXT NULL
- `last_auth_error` TEXT NULL
- `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
- `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

Migration:
- New migration (next revision after current head) to create `amazon_login_profiles`.
- No backfill from singleton state (since that path is being removed and migration was not run).

## 3) DB facade API (decision complete)
Add methods:
- `list_amazon_login_profiles(*, enabled_only: bool = False) -> list[AmazonLoginProfileDB]`
- `create_amazon_login_profile(*, profile_key: str, display_name: str, enabled: bool = True, sort_order: int = 0) -> AmazonLoginProfileDB`
- `update_amazon_login_profile(*, profile_key: str, display_name: str | None = None, enabled: bool | None = None, sort_order: int | None = None) -> AmazonLoginProfileDB`
- `delete_amazon_login_profile(*, profile_key: str) -> None`
- `set_amazon_login_context_id(*, profile_key: str, context_id: str | None) -> AmazonLoginProfileDB`
- `record_amazon_login_auth_result(*, profile_key: str, status: str, error: str | None = None) -> None`

Ordering for list:
- `ORDER BY sort_order ASC, profile_id ASC`.

## Agent and CLI Interfaces

## 4) CLI commands
Add/standardize:
- `transactoid amazon-login add --key <key> --name <name> [--order <n>] [--disabled]`
- `transactoid amazon-login list [--enabled-only]`
- `transactoid amazon-login update --key <key> [--name <name>] [--order <n>] [--enable|--disable]`
- `transactoid amazon-login remove --key <key>`
- `transactoid amazon-login clear-context --key <key>`

Validation:
- `update` requires at least one mutable field.
- `add` rejects duplicate key.
- `remove/clear/update` on unknown key returns explicit error.

## 5) Agent tools (multiple dedicated tools, strong contracts)
Add separate tools (no operation multiplexer):
- `list_amazon_logins()`
- `add_amazon_login(profile_key, display_name, enabled=True, sort_order=0)`
- `update_amazon_login(profile_key, display_name=None, enabled=None, sort_order=None)` (must include at least one update field)
- `remove_amazon_login(profile_key)`
- `clear_amazon_login_context(profile_key)`

Optional but recommended for stronger intent:
- `enable_amazon_login(profile_key)`
- `disable_amazon_login(profile_key)`

Register all in tool registry and classify as `execute` kind in runtime protocol map.

## 6) Presenter updates
In ACP presenter:
- Input formatting per new tool name.
- Output formatting:
  - list tools as JSON block
  - mutations as concise confirmations
  - explicit error message pass-through (no generic “Unknown error” when message exists).

## Scrape Execution Flow (Core Behavior)

## 7) Profile selection
`scrape_amazon_orders` uses:
- all `enabled=true` profiles in configured order.
- if none: return actionable error (“no enabled Amazon login profiles configured”).

## 8) Sequential auth phase (required)
For each profile in order:
1. If `browserbase_context_id` is null:
   - create context via `StagehandBrowserbaseBackend.create_context()`
   - persist context ID for this profile
   - mark this profile as requiring login now.
2. Validate active login status with that context:
   - open Browserbase session and navigate to orders page.
   - if still logged in: mark `ready`.
   - if redirected to signin: run interactive login mode for that profile.
3. After login attempt, re-check:
   - if authenticated: mark ready.
   - if not: mark failed, record auth error, continue to next profile.

Important:
- Only profiles that are configured and unauthenticated appear in login flow.
- Already-authenticated profiles do not prompt login.

## 9) “Refresh context id” rule when invalid
When context is active but login invalid:
- perform reauth for that profile.
- if platform/API requires recreation (explicit context/session error), generate new context ID and persist it (refresh).
- otherwise keep same context ID and update auth status.
- record `last_auth_status` and `last_auth_error`.

## 10) Parallel scrape phase
- Run scrape concurrently for all `ready` profiles.
- Concurrency cap: `min(4, ready_count)` default.
- Retry once per profile on failure.
- Continue all profiles even if one fails.

## 11) Persistence and merge
- Persist each successful profile’s results with existing upsert logic:
  - order uniqueness by `order_id`
  - item uniqueness by `(order_id, asin)`
- This yields union semantics across profiles.
- Aggregate counts at run level.

## 12) Result contract for scrape
Return:
- top-level:
  - `status`: `success | partial | error`
  - `orders_created`
  - `items_created`
  - `profiles_total`
  - `profiles_ready`
  - `profiles_succeeded`
  - `profiles_failed`
  - `message` (summary)
- per-profile:
  - `profile_results: [{profile_key, display_name, status, orders_created, items_created, message}]`

Status rules:
- `success`: all enabled profiles succeeded.
- `partial`: at least one success and at least one failure.
- `error`: zero successful profiles.

## Logging and Diagnostics
Add structured logs with profile context at each step:
- profile resolution
- context create/load/refresh
- auth check result
- login flow start/end
- scrape start/end
- retry attempt
- persistence start/end and error details

Preserve specific DB/network/auth errors in returned per-profile messages.

## Testing Plan

## 13) DB/facade tests
- profile CRUD
- ordering/enabled filtering
- set/clear context
- auth status recording
- duplicate key handling
- unknown profile handling

## 14) Orchestrator flow tests
- no enabled profiles -> error
- missing context -> created -> login required
- valid context -> no login prompt
- invalid context -> reauth path
- sequential auth ordering
- parallel scrape dispatch
- retry-once behavior
- aggregate status computation

## 15) Tool contract tests
For each new agent tool:
- happy path
- validation errors
- not-found/duplicate errors
- response shape checks

## 16) Presenter/runtime tests
- tool kind mapping includes new tools as `execute`
- ACP presenter input/output coverage for each tool

## 17) End-to-end integration test (mocked backend)
- two+ profiles, mixed auth states
- one failure with retry then success/failure
- overlapping orders across profiles dedupe correctly

## Rollout and Compatibility
1. Merge DB/profile table migration.
2. Deploy code with new tools and profile-based scrape flow.
3. Ensure runbooks switch from env singleton context to profile configuration.
4. Remove stale references/docs for singleton state.
5. Keep scrape tool name stable (`scrape_amazon_orders`) for compatibility.

## Assumptions and Defaults
- `scrape_amazon_orders` always targets all enabled profiles.
- Sequential login/reauth, parallel scrape.
- Retry once per profile.
- Union merge persistence.
- Multiple dedicated agent tools are preferred over one operation-based tool.
