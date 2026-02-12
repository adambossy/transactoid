# Investments Consent + Activity Ingestion Patch Plan

## Summary
Add Plaid investments consent and ingest investment-account activity (including Morgan Stanley `...9320`) into existing transaction tables, while applying classification rules so spending analytics include “money movement” activity by default and exclude investment-income/trade activity by default.

This plan assumes:
- Product scope: **Investments only**
- Storage model: **Reuse existing `plaid_transactions` + `derived_transactions`**
- Consent behavior: **Auto prompt path on consent error**
- Reporting behavior: **Type-aware default** (include money movement, exclude investment-income/trade)

## Current-state grounding
- Link token creation currently hardcodes `products=["transactions"]` in `src/transactoid/adapters/clients/plaid_link.py`.
- Sync pipeline only pulls `/transactions/sync` via `src/transactoid/tools/sync/sync_tool.py`.
- Plaid institution supports `investments`, but current Item lacks consent; direct calls return `ADDITIONAL_CONSENT_REQUIRED`.
- Existing dedupe/refresh work is already in place for item identity consistency.

## Public API / interface changes
1. `PlaidClient.create_link_token(...)`
- Extend signature to support optional:
  - `required_if_supported_products: list[str] | None`
  - `access_token: str | None` (for update-mode Link to add consent for existing Item)
- Request payload changes:
  - include `required_if_supported_products` when provided
  - include `access_token` when provided (update mode)

2. `create_link_token_and_url(...)` in `src/transactoid/adapters/clients/plaid_link.py`
- Add optional parameter:
  - `products: list[str] | None = None`
  - `required_if_supported_products: list[str] | None = None`
  - `access_token: str | None = None`
- Remove hardcoded products and pass-through to `create_link_token_fn`.

3. `PlaidClient.connect_new_account(...)`
- Add optional parameter:
  - `products: list[str] | None = None`
  - `required_if_supported_products: list[str] | None = None`
- Default for new links:
  - `products=["transactions"]`
  - `required_if_supported_products=["investments"]` (ensures consent if institution supports it)

4. New Plaid client methods
- `get_investment_transactions(access_token, start_date, end_date, options...)`
- `get_investment_holdings(access_token)` (optional now, useful for future holdings UI)
- Strong typed model(s) for investments transaction payload fields needed for normalization.

5. Sync summary (non-breaking additive fields)
- Extend `SyncSummary.to_dict()` output with:
  - `investment_added`
  - `investment_skipped_excluded`
  - `consent_required_items` (list of item IDs or count)

## Data model and normalization design
Reuse existing immutable source table (`plaid_transactions`) with `source` discriminator:
- Existing banking rows keep `source="PLAID"`.
- Investment-activity rows use `source="PLAID_INVESTMENT"`.

External IDs
- Banking: existing Plaid `transaction_id`.
- Investment: `investment_transaction_id` as `external_id`.
- This avoids collisions under unique `(external_id, source)`.

Account linkage
- `account_id` from investment transaction.
- `item_id` always persisted (using migrated/canonical item ID).

Amount/sign
- Preserve Plaid-provided signed `amount` semantics after conversion to cents.
- Do not reinterpret signs by category; keep source of truth immutable.

Merchant descriptor mapping
- `merchant_descriptor = name` (fallback `security.name` if present and `name` empty).

## Inclusion/exclusion policy (decision complete)
Use deterministic rule function `_investment_activity_reporting_mode(...)`:
- `INCLUDE_BY_DEFAULT`:
  - Zelle payment, automated payment, direct deposit, cash transfer, ACH/check/payment style entries.
  - Heuristic by Plaid fields:
    - transaction `type/subtype` and `name`
    - keyword map: `zelle`, `direct dep`, `cash transfer`, `payment`, `ach`, `wire`, `check`.
- `EXCLUDE_BY_DEFAULT`:
  - Dividend, interest income, margin interest, trade activity, unsettled trade, security transfer, partnership distributions, FX, and clearly security-market events.
  - Keyword + subtype map: `dividend`, `interest`, `trade`, `security`, `margin`, `distribution`, `fx`.

Persistence behavior
- Persist **all** investment transactions into source tables (immutability/completeness).
- In derived/reporting path:
  - For excluded modes, set a marker (`is_investment_excluded_default=true`) in derived metadata (see below) and exclude in default analytics queries.
  - For included modes, process normally into derived spending analytics.

If no metadata column exists today:
- Add nullable `reporting_mode` column to `derived_transactions` (`DEFAULT_INCLUDE`, `DEFAULT_EXCLUDE`) via migration.
- Keep backward compatibility by treating NULL as `DEFAULT_INCLUDE`.

## Sync flow changes
1. Per-item sync pipeline remains parallel.
2. For each item:
- Run existing `/transactions/sync`.
- Additionally run investments fetch path:
  - rolling window initial default: last 730 days on first run per item
  - incremental thereafter via timestamp watermark (see cursor section).

3. Consent error handling
- If investments endpoint returns `ADDITIONAL_CONSENT_REQUIRED`:
  - Do not fail whole sync.
  - Record item in `consent_required_items`.
  - Return actionable message:
    - “Investments consent required for item `<id>`. Run connect/update flow.”
  - If invocation context supports interactive flow, auto-trigger update-mode link token with `access_token` and required investments product.

4. Cursor/watermark management
- Keep existing `sync_cursor` for `/transactions/sync`.
- Add per-item investments watermark storage:
  - Add `investments_synced_through` (timestamp/date) to `plaid_items`.
  - On initial run, backfill 730 days.
  - On incremental runs, query from watermark minus 7-day safety overlap and dedupe by `(external_id, source)`.

## CLI / operator workflow updates
1. `connect_new_account` flow
- New links request transactions + investments consent (required-if-supported).
2. Add command: `plaid-add-investments-consent --item-id <id>`
- Generates update-mode link token for existing Item (`access_token` passed).
- Opens browser flow and exchanges token as existing connect flow.
- Uses existing item identity migration path if Plaid rotates item ID.
3. Sync output
- Show investment ingest counts and consent-needed warnings.

## Edge cases and failure modes
- Institution supports investments but returns no investment transactions:
  - treat as success with `investment_added=0`.
- Duplicate replays from overlap window:
  - absorbed by upsert uniqueness on `(external_id, source)`.
- Item ID rotates during consent update:
  - use existing `migrate_plaid_item_identity(...)`.
- Misclassified activity types:
  - classification function is centralized and unit-tested; default-safe behavior is to classify uncertain entries as `EXCLUDE` only when strong signal exists, otherwise `INCLUDE`.
- No interactive environment available for auto-prompt:
  - emit explicit remediation command and keep sync successful.

## Tests and scenarios
1. Unit tests: Plaid link token payload
- Verifies `required_if_supported_products=["investments"]` included.
- Verifies update-mode token includes `access_token`.

2. Unit tests: investments normalization
- Input-first fixtures for investment rows including:
  - `Dividend`, `Interest Income`, `Trade`, `Cash Transfer`, `Direct Deposit`, `Zelle Payment`.
- Assert normalized `source`, `external_id`, `amount_cents`, `reporting_mode`.

3. Unit tests: classification policy
- Explicit expected include/exclude for screenshot-derived examples:
  - Include: Zelle, automated payment, direct deposit, cash transfer
  - Exclude: dividend, interest income, trade-like rows

4. Sync tests
- Mixed item where banking sync succeeds and investments consent missing:
  - sync returns success + consent_required indicator (not fatal).
- Investments data available:
  - rows upserted with `source="PLAID_INVESTMENT"`.
  - derived rows tagged with expected reporting_mode.
- Incremental watermark:
  - second run does not duplicate rows.

5. Integration test (optional but recommended)
- Mock Plaid responses for `/transactions/sync` + `/investments/transactions/get` in one item and validate final summary counters.

## Migration plan
1. DB migration:
- `plaid_items.investments_synced_through` nullable datetime/date.
- `derived_transactions.reporting_mode` nullable string (or enum-like constrained text).
2. Backfill:
- Leave NULL existing rows (interpreted as include).
- No destructive migration.

## Rollout strategy
1. Phase 1
- Ship consent request in new links + consent-needed warnings in sync.
2. Phase 2
- Enable investments ingestion + classification.
3. Phase 3
- Optional: holdings ingestion and investment-specific reporting surfaces.

## Acceptance criteria
- Existing account `...9320` can ingest activity after consent update.
- Money movement items from investment account appear in default analytics.
- Dividend/interest/trade categories are excluded from default spending analytics.
- No regression in depository `/transactions/sync`.
- Sync remains successful when investments consent is absent, with clear actionable output.

## Assumptions and defaults
- Keep current taxonomy/categorizer pipeline; no taxonomy overhaul in this patch.
- Use keyword+Plaid-field classification (not ML) for deterministic behavior.
- 730-day initial investments history window.
- Unknown activity types default to include unless strong investment-income/trade signal exists.
