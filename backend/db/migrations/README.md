# Penny Migration Chain

The chain is now self-contained: `000_baseline_schema` is the root revision and
creates the baseline tables (`merchants`, `categories`, `plaid_transactions`,
`derived_transactions`, etc.). Migrations `001`–`005` build on top of it.
`alembic upgrade head` from an empty database reproduces exactly what
`Base.metadata.create_all` (`DB.create_schema`) produces.

## Fresh database

Either path works and yields the same schema:

```bash
# Option A — build the whole schema through Alembic
alembic upgrade head
```

```python
# Option B — create_all + stamp (this is what bootstrap() does on startup)
from penny.db import get_db
get_db().create_schema()
```
```bash
alembic stamp head
```

Note: `bootstrap()` still calls `create_schema()` (idempotent) on every backend
startup, so a server-managed DB is already at the full schema. Run
`alembic stamp head` once to record that for future migrations.

## Existing database already on the full schema (e.g., prod Neon)

A DB created via `create_all` already has every baseline table, so do **not**
run the baseline against it. Just record that it is current:

```bash
alembic stamp head
```

Do **not** `alembic stamp base` then `alembic upgrade head` — the baseline would
try to recreate existing tables and fail.

## Migration chain

| Revision | Description |
|----------|-------------|
| 000 | Baseline schema — create the 11 pre-001 tables (root revision) |
| 001 | Add transaction_items table and split provenance columns to derived_transactions |
| 002 | Add email_receipts and pending_receipt_matches tables |
| 003 | Add refund linkage columns to derived_transactions |
| 004 | Add account_sign_conventions table |
| 005 | Seed account_sign_conventions from the institution mapping (data migration) |

After upgrading through 005, historical derived rows for expense_negative
accounts were normalized by a one-time backfill (migration 005 seeds
conventions but does not rewrite existing rows, and the backfill calls the LLM
categorizer, which has no business running inside `alembic upgrade`). That
backfill has been applied to production and going-forward rows are normalized
at ingest by the sync path, so the script is spent; it is archived at
`history/backfill_sign_conventions.py`.
