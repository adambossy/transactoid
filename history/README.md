# history/ — non-canonical artifacts

Spent, point-in-time artifacts kept for **history, not truth** (see the
"Canonical vs. non-canonical artifacts" section in `AGENTS.md`). Nothing here
describes how Penny runs today; it is kept to reconstruct *what happened and
why* — debugging, archaeology, tracing the lineage of a design.

**Do not** treat anything here as a source of truth, wire it into the app, or
maintain it (no refactors, no lint, no keeping it building). It lives outside
the canonical packages and outside the recurring dev tooling in
`backend/scripts/`, and it stays out of the verification gate.

## Contents

- `seed_sign_conventions.py` — the original one-off that seeded
  `account_sign_conventions` from the institution mapping. Superseded by the
  data migration `backend/db/migrations/005_seed_account_sign_conventions.py`,
  which is now the canonical seeding path. Kept as the record of the manual
  step it replaced.
- `backfill_sign_conventions.py` (+ `test_backfill_sign_conventions.py`) — the
  one-time backfill that retroactively sign-normalized historical
  `derived_transactions` rows for expense_negative accounts, run once after
  migration 005. Going-forward rows are sign-normalized at ingest by the sync
  path, so the backfill is spent. Kept as the record of the cut-over.
