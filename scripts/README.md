# Scripts

This directory contains small, focused command-line helpers for the project.

## Plaid CLI (`plaid_cli.py`)

A standalone command-line tool for working with the Plaid API. It has **no dependencies on the rest of the project** and uses only the Python standard library.

It supports two main commands:

- `sandbox-link`: create a **sandbox** Plaid item and write its `access_token` to a JSON file.
- `transactions`: fetch and print transaction history for an existing `access_token`.

### Requirements

- Python 3.12+
- A Plaid account and API keys

Set the following environment variables before use:

```bash
export PLAID_CLIENT_ID="your-client-id"
export PLAID_SECRET="your-secret"
export PLAID_ENV="sandbox"   # or development / production
```

For fetching transactions, you can optionally set:

```bash
export PLAID_ACCESS_TOKEN="your-access-token"
```

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
