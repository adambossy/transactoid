---
id: tier-2
label: Tier 2 — Smarter merchant normalization
parent: root
sections: [goal, schema-changes, approach]
crosslinks: [tier-2-sampling, tier-2-normalizer, tier-2-validation]
---

# Tier 2 — Smarter merchant normalization

Fix the root cause so the `merchants` graph carries semantic meaning. Once merchants encode "who" instead of "what message Plaid sent," `recategorize_merchant` becomes useful again and most per-row touch-ups disappear.

## Requirements

- Recurring payments to the same counterparty resolve to one merchant, not a new one per send.
Channels where purpose isn't knowable from the defkf
The extraction logic is reviewable and versioned, and itsff
- The change carries no risk to historical data — it applies going forward only.

## goal — Goal

Today `normalize_merchant_name(descriptor) -> str` returns a lookup key produced by naive lowercase/strip/collapse, with `display_name` hardcoded to the raw descriptor. That can't tell a counterparty apart from per-transaction noise. Tier 2 replaces it with a normalizer that understands wrapper descriptors and extracts identity from noise.

## schema-changes — Schema changes

Two nullable columns on `merchants` cache metadata already implicit in the name:

```sql
ALTER TABLE merchants
  ADD COLUMN source_channel VARCHAR(50),   -- 'direct' | 'zelle' | 'venmo' | 'atm' | 'paypal' | 'stripe' | ...
  ADD COLUMN counterparty   VARCHAR(200);  -- e.g. 'Tania (XXX-4352)' or 'Rory Mabin'
```

`source_channel` defaults to `'direct'`; `counterparty` is `NULL` for direct merchants. Add these via a new alembic migration (`006_add_merchant_metadata_columns.py`) — not a raw `ALTER TABLE` — and mirror them on the `Merchant` ORM model so the SQLite `create_all` path stays in sync. There is deliberately no `deprecated_at` column: its only purpose was soft-deleting merchants orphaned by a backfill, and the backfill is dropped in favor of [validation](tier-2/validation.html).

## approach — Approach, in three steps

Tier 2 is three moves, each its own page:

1. [Collect descriptor samples](tier-2/sampling.html) — pull the real corpus first; extraction rules are only as good as our knowledge of the formats.
2. [The LLM normalizer](tier-2/normalizer.html) — a versioned rule repository plus an LLM call that returns structured merchant identity.
3. [Validation, not backfill](tier-2/validation.html) — a human-in-the-loop review gate; apply going forward, defer repointing history.
