# Scripts

This directory contains small, focused command-line helpers for the project.

## Legacy Category Migration (`migrate_legacy_categories.py`)

Convert the exported `fa_categories_rows.csv` file from the legacy Fire Ant
deployment into the current two-level taxonomy schema.

Key behaviors:

- Normalizes every legacy `code` into deterministic taxonomy keys using a
  slugified parent/child pattern (e.g., `Food & Dining` → `food_dining`,
  `Groceries` → `food_dining.groceries`).
- Preserves the legacy `sort_order` to keep parents and children ordered.
- Emits an optional taxonomy YAML file (`--output-yaml`) for use with the
  existing `seed_taxonomy` flow.
- Can directly replace the records in the configured database when `--apply`
  is supplied.

Run it from the repository root:

```bash
uv run python -m scripts.migrate_legacy_categories migrate \
  --input fa_categories_rows.csv \
  --output-yaml configs/taxonomy.generated.yaml \
  --apply
```

Use `--database-url` to override `DATABASE_URL`, or omit `--apply` for a
dry-run preview.

## Plaid CLI (`plaid_cli.py`)

A standalone command-line tool for working with the Plaid API. It has **no dependencies on the rest of the project** and loads credentials from the repo’s `.env` file via [`python-dotenv`](https://pypi.org/project/python-dotenv/).

It supports three main commands:

- `sandbox-link`: create a **sandbox** Plaid item and write its `access_token` to a JSON file.
- `exchange-public-token`: exchange a Plaid Link `public_token` (sandbox, development, or production) for an `access_token`.
- `transactions`: fetch and print transaction history for an existing `access_token`.

### Requirements

- Python 3.12+
- A Plaid account and API keys
- [`python-dotenv`](https://pypi.org/project/python-dotenv/) installed (`pip install python-dotenv` or `uv add python-dotenv`)

The script automatically loads environment variables from `.env` in the project root. Make sure that file (or your shell) defines:

```bash
export PLAID_CLIENT_ID="your-client-id"
export PLAID_ENV="sandbox"   # or development / production
export PLAID_SANDBOX_SECRET="your-sandbox-secret"
export PLAID_DEVELOPMENT_SECRET="your-development-secret"   # if you use development
export PLAID_PRODUCTION_SECRET="your-production-secret"     # if you use production
```

For fetching transactions, you can optionally set:

```bash
export PLAID_ACCESS_TOKEN="your-access-token"
```

> **Tip:** If you only work in one environment, you only need to set the matching secret.

### 1. Create a sandbox access token

This command only works when `PLAID_ENV=sandbox`. It will:

1. Call `/sandbox/public_token/create` to create a sandbox item.
2. Exchange the `public_token` via `/item/public_token/exchange`.
3. Write an access-token JSON file (by default `plaid_access_token.json`).

Run from the repo root:

```bash
python scripts/plaid_cli.py sandbox-link \
  --institution-id ins_109508 \
  --output plaid_access_token.json
```

After it runs, you can export the token for convenience (requires `jq`):

```bash
export PLAID_ACCESS_TOKEN="$(jq -r .access_token plaid_access_token.json)"
```

### 2. Exchange a Plaid `public_token`

When you run Plaid Link (web, mobile, or sandbox), it returns a short-lived `public_token`. Convert it to a long-lived `access_token` with the new subcommand:

```bash
python scripts/plaid_cli.py exchange-public-token \
  public-sandbox-1234-5678-90ab-cdef \
  --output plaid_access_token.json
```

- Works with any `PLAID_ENV` (`sandbox`, `development`, or `production`).
- `--output` is optional; if provided, the script saves token details (token, item_id, environment, timestamps) as JSON.
- The access token is always printed to stdout so you can copy/paste it immediately.

### 2. Fetch transactions

Fetch transactions for an existing access token over a date range.

Using `PLAID_ACCESS_TOKEN` from the environment (last 30 days by default):

```bash
python scripts/plaid_cli.py transactions
```

Or passing the access token and dates explicitly:

```bash
python scripts/plaid_cli.py transactions \
  --access-token "$PLAID_ACCESS_TOKEN" \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --count 200
```

- `--count` controls the maximum number of transactions to return (default: 100).
- `--start-date` and `--end-date` use the format `YYYY-MM-DD`.

To see the full Plaid `/transactions/get` JSON response instead of just the
`transactions` array, add `--raw`:

```bash
python scripts/plaid_cli.py transactions --raw
```

### Notes

- `plaid_cli.py` is intentionally independent of the rest of the `transactoid` package.
- It is safe to use it outside this repository as a generic Plaid CLI helper.
