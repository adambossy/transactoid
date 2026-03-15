# Plan: Clean Up Existing PLAID_INVESTMENT Duplicate Transactions

## Context

Morgan Stanley's Plaid connection returns the same cash transactions (ATM withdrawals, Zelle payments) through both `/transactions/sync` (source=PLAID) and `/investments/transactions/get` (source=PLAID_INVESTMENT). A sync-time dedup was added on Feb 25, 2026 (commit `3e8c2c1`), but duplicates inserted between Feb 13–19 still exist in the database. This plan adds a CLI command to archive these duplicates to R2 and delete them.

## Changes

### 1. New facade method: `find_investment_dupes_with_plaid_match`
- Self-join `plaid_transactions` as `inv` (source=PLAID_INVESTMENT) against `plaid` (source=PLAID) on `(item_id, account_id, posted_at, amount_cents)`
- Returns the PLAID_INVESTMENT rows (full ORM objects, expunged from session)

### 2. Extracted archival function: `archive_investment_dupes_to_r2`
- New module `src/transactoid/adapters/storage/archive.py`
- Serializes records to JSON, uploads to R2
- Swallows `R2StorageError` with warning log
- SyncTool's `_archive_investment_dupes_to_r2` refactored to delegate here

### 3. CLI command: `plaid-cleanup-investment-dupes`
- Dry-run by default, `--apply` to actually delete
- Groups duplicates by item_id, prints per-item report
- Archives to R2 with `investment-dedup-cleanup` prefix before deleting
- Intentional CLI/MCP parity exception (one-off cleanup)

## Verification
- 572 tests passing
- ruff, mypy, deadcode all clean
