# Penny Migration Chain

The penny schema baseline predates this migration chain (bootstrapped via
`create_schema()` / `Base.metadata.create_all`). These migrations assume the
baseline tables (`merchants`, `categories`, `plaid_transactions`,
`derived_transactions`, etc.) already exist.

## Existing database (e.g., Neon)

```bash
# Tell Alembic the baseline exists without running any migrations
alembic stamp base

# Apply all migrations in this chain
alembic upgrade head
```

## Fresh database

```python
# create_schema() now includes these tables — run it first
from penny.db import get_db
get_db().create_schema()
```

Then stamp so Alembic knows the state:

```bash
alembic stamp head
```

## Migration chain

| Revision | Description |
|----------|-------------|
| 001 | Add transaction_items table and split provenance columns to derived_transactions |
| 002 | Add email_receipts and pending_receipt_matches tables |
| 003 | Add refund linkage columns to derived_transactions |
| 004 | Add account_sign_conventions table |
| 005 | Seed account_sign_conventions from the institution mapping (data migration) |

After upgrading through 005, run `scripts/backfill_sign_conventions.py`
once to normalize historical derived rows for expense_negative accounts.
The migration seeds conventions but does not rewrite existing rows — the
backfill calls the LLM categorizer, which has no business running inside
`alembic upgrade`.
