# Plaid account dedupe plan

## Goals
- Persist Plaid account metadata at link time so dedupe can be DB-only.
- Dedupe new links by institution + mask and keep the existing canonical Item.
- Provide a one-off CLI command to clean up existing duplicates with a dry-run default.

## Current state
- Only `plaid_items` table exists; no account-level table.
- Link flow saves the Plaid Item only.
- Transactions store `account_id` but no persisted account metadata for matching.

## Dedupe key and policy
- Dedupe key: `(institution_id, mask)` from Plaid account metadata.
- Canonical policy: keep the existing Item; drop the newly linked Item.
- “Drop” behavior:
  - During link: do not insert the new Item or its accounts.
  - Script: delete the local DB row for the duplicate Item (no Plaid API calls).

## Implementation steps
1) Schema
   - Add `plaid_accounts` table (SQLAlchemy model) with:
     - `account_id` (primary key, Plaid account id)
     - `item_id` (FK to `plaid_items.item_id`)
     - `mask`, `type`, `subtype`, `name`, `official_name` (nullable)
     - `institution_id`, `institution_name` (nullable)
     - `created_at`, `updated_at`
   - Consider FK cascade delete from `plaid_items` to `plaid_accounts`.

2) DB facade helpers
   - Insert/update `plaid_accounts` for an Item.
   - Fetch account dedupe keys for an Item.
   - Look up existing Items by dedupe key.
   - Delete a Plaid Item (and associated accounts if no cascade).

3) Link flow changes
   - After exchanging public token and before persisting:
     - Fetch accounts via `/accounts/get`.
     - Build dedupe keys `(institution_id, mask)`.
     - If any key exists already: skip insert and return a “duplicate” message.
   - If no duplicate: save Plaid Item then save Plaid accounts.

4) One-off CLI command (main Typer app)
   - Command: `plaid-dedupe-items` (name TBD).
   - Behavior:
     - Dry-run default; `--apply` to delete.
     - Group Items by dedupe key via stored `plaid_accounts`.
     - Keep earliest created Item (or deterministic tie-breaker).
     - Print concise stdout report: kept item, deleted items, skipped items (no accounts).

5) Tests
   - Dedupe key detection using minimal fixtures.
   - Link flow skip-on-duplicate behavior.
   - CLI grouping and delete behavior; dry-run output shape.
   - For items without `plaid_accounts`, ensure they are reported and skipped.

## Open choices
- Command naming and exact output format.
- Tie-breaker for canonical selection (earliest `created_at` vs stable ID).
- Whether to add a unique constraint on `(institution_id, mask)` in `plaid_accounts`.
