# Individual Recategorization & Smarter Merchant Normalization

**Date:** 2026-06-11
**Status:** Proposed
**Scope:** Tier 1 and Tier 2 are in scope. Tier 3 and Tier 4 are noted for context but **not in scope** for this plan.

## Background

The categorization pipeline today uses `merchant_id` as both the *identity* of a counterparty and the *handle* for bulk recategorization (`recategorize_merchant`). This breaks down for **wrapper descriptors** — Zelle, Venmo, ATM withdrawals, payment processors (Bambora, Square, Stripe) — in two distinct failure modes:

1. **Fragmentation:** descriptors with embedded per-transaction entropy (e.g., Zelle confirmation hashes) produce a new `merchants` row per send. Two payments to the same counterparty get different `merchant_id`s. The current naive normalizer just lowercases and strips digits, which doesn't strip the alphabetic portion of a confirmation hash.
2. **Collapse:** descriptors with fixed identifying text but variable purpose (e.g., `ATM Withdrawal 896 MANHATTAN AV`) collapse semantically distinct activity into one `merchant_id`. Today, 16 ATM withdrawals at the same location share `merchant_id=1534`, but they represent at least three different categories of spend (nanny pay, gift cash, miscellaneous).

Concrete examples observed in the current database:

| Symptom | Example |
|---|---|
| Fragmentation | Two $666 Zelles to Tania (XXX-4352) have `merchant_id` 2382 and 2393 because the confirmation hashes differ |
| Collapse | 16 ATM withdrawals at `896 MANHATTAN AV` all share `merchant_id=1534` despite encoding nanny pay ($1,040–$1,075), one gift withdrawal ($253.50), and partial-pay variants ($573.50) |

The downstream consequence: there is no clean way to recategorize a single transaction. `recategorize_merchant` is a bulk operation; the MCP surface does not expose a per-transaction recategorize tool. The only workaround today is raw `UPDATE` SQL via `run_sql`, which violates the project's "no raw write SQL" guardrail.

## Tier 1 — Per-transaction recategorize tool (in scope)

### Goal

Close today's tooling gap so individual transactions can be recategorized cleanly without bypassing guardrails.

### Schema changes

**None.** The data model already supports per-row category mutation. `derived_transactions.category_id`, `category_method`, `category_assigned_at`, and `is_verified` are all already present. The audit table `transaction_category_events` already records category transitions.

### New MCP tool

```
recategorize_transaction(
  transaction_id: int,
  category_key: str,
  reason: str | None = None,
  verify: bool = True,
) -> {updated: bool, event_id: int}
```

The tool:

1. Resolves `category_key` to `category_id` via the `categories` table. The column is `categories.key` (not `category_key`); resolution filters on the active partial unique index (`deprecated_at IS NULL`), so deprecated or unknown keys are rejected.
2. Updates `derived_transactions` for the row:
   - `category_id` → the new id
   - `category_method` → `'manual'`
   - `category_model` → `NULL`
   - `category_assigned_at` → `NOW()`
   - `updated_at` → `NOW()`
   - `is_verified` → `TRUE` (if `verify=True`; otherwise leaves the existing value)
3. Inserts a `transaction_category_events` row with `method='manual'`, the from/to categories, optional `reason`, and `created_at=NOW()`.

**Implementation note:** the atomic update-plus-event logic already exists in the DB façade as `_apply_category_updates(...)` (it takes `{transaction_id: category_id}`, sets the category fields, and inserts the audit event in one transaction). Reuse it. It currently has a `reset_verified` flag whose only capability is forcing `is_verified=False`. **Replace** `reset_verified` with an `is_verified: bool | None = None` parameter: `True`/`False` sets the column to that value, `None` leaves the existing value untouched. `recategorize_transaction(verify=True)` then passes `is_verified=True` through the same path; existing callers that relied on `reset_verified=True` pass `is_verified=False`. The provenance CHECK constraint covers `(category_id, category_method, category_assigned_at)` only — setting `category_model=NULL` while those three are non-NULL is constraint-safe.

### Interaction with existing `recategorize_merchant` behaviour

The existing `recategorize_merchant` tool already skips verified rows ("Recategorize all unverified transactions for a merchant"). Because `recategorize_transaction` sets `is_verified=true` by default, **manual fixes are automatically protected from future bulk operations**. No additional locking primitive needed.

### Verification

- Smoke test: run `recategorize_transaction` on a known row; confirm `derived_transactions` row updated, audit event written, and a subsequent `recategorize_merchant` for the same merchant skips this row.
- Round-trip test: recategorize a row twice; verify two audit events exist with correct from/to chain.

### Effort estimate

Hours, not days. The tool body is ~30 lines plus a thin MCP wrapper, reusing `_apply_category_updates` with its `reset_verified` flag replaced by the `is_verified: bool | None` parameter.

## Tier 2 — Smarter merchant normalization for wrapper descriptors (in scope)

### Goal

Fix the root cause of the wrapper-merchant problem so the `merchants` graph actually carries semantic meaning. Once merchants encode "who" (not "what message Plaid happened to send"), `recategorize_merchant` becomes useful again and most individual transaction touch-ups disappear.

### First task: collect real descriptor samples

The extraction rules are only as good as our knowledge of the real descriptor formats, which are institution-specific. **Before writing any extraction rule**, pull the actual corpus from the database:

```sql
SELECT DISTINCT merchant_descriptor, COUNT(*)
FROM plaid_transactions
GROUP BY merchant_descriptor
ORDER BY COUNT(*) DESC;
```

Run this against the `penny-test` Neon branch (real prod-mirrored data) and survey a **broad** swath — don't assume the channels are just Zelle / Venmo / ATM / processor / direct. The point of this pass is discovery: find every wrapper/vendor pattern present (P2P apps, billers, processors, transfer types, etc.) so we can pre-define an extraction-rule entry for each. The real samples then become the eval fixtures (see *Verification*) and the seed examples embedded in the rule descriptions.

### Schema changes

**Existing columns kept.** Additions to `merchants` for cached, queryable metadata that is already implicitly encoded in `normalized_name`:

```sql
ALTER TABLE merchants
  ADD COLUMN source_channel VARCHAR(50),   -- 'direct' | 'zelle' | 'venmo' | 'atm' | 'paypal' | 'stripe' | 'bambora' | ...
  ADD COLUMN counterparty   VARCHAR(200);  -- e.g., 'Tania (XXX-4352)' or 'Rory Mabin'
```

Both nullable. `source_channel` defaults to `'direct'` for non-wrapper merchants. `counterparty` is `NULL` for direct merchants (where the merchant itself is the counterparty).

(No `deprecated_at` column — its only purpose was soft-deleting merchants orphaned by the backfill, and the backfill is dropped in favor of a validation step. See *Validation* below.)

**Migration mechanics.** The repo now has an alembic chain (`backend/db/migrations/`, baseline `000` through `005`). Add a new migration (`006_add_merchant_metadata_columns.py`) for the two columns — do **not** use a raw `ALTER TABLE`. Because dev/test still default to SQLite via `Base.metadata.create_all` (`facade.create_schema`), also update the `Merchant` ORM model in `penny/adapters/db/models.py` so both paths stay in sync (this dual-update pattern is already documented in the model's CHECK-constraint NOTEs).

### Normalizer changes

The normalizer learns about wrapper descriptors and how to extract identity vs. discard noise. **It does this with an LLM call, not deterministic per-vendor matchers.** Hand-written `is_zelle`/`extract_zelle_party`-style functions are brittle (institution-specific formats), and one matcher per vendor doesn't scale to the long tail of wrappers. Instead:

- Maintain a **repository of extraction rules** — one entry per known channel/vendor (Zelle, Venmo, ATM, PayPal, Stripe, Bambora, …), each a plain-English description of *what to extract* (counterparty, phone tail, sub-merchant) and *what to discard* (confirmation hashes, note fields, per-transaction entropy). These descriptions codify what the deterministic `extract_*` functions would have done, but in natural language the LLM interprets. Keep them in-repo (a YAML/markdown file under `backend/`, loaded like the existing prompt/taxonomy assets) so they're versioned and reviewable.
- The normalizer passes the raw descriptor plus the relevant rules to an LLM call that returns a structured `NormalizedMerchant`:

```python
@dataclass
class NormalizedMerchant:
    normalized_name: str     # stable identity key, e.g. "zelle:tania:4352"
    display_name: str        # e.g. "Zelle: Tania (XXX-4352)"
    source_channel: str      # "zelle" | "venmo" | "atm" | "direct" | ...
    counterparty: str | None # "Tania (XXX-4352)" | None for direct merchants

def normalize_merchant(descriptor: str) -> NormalizedMerchant:
    # LLM call: descriptor + extraction-rule repository -> structured fields.
    # For direct merchants (no wrapper detected) the model falls back to the
    # existing naive normalization (lowercase / strip / collapse).
    ...
```

Build notes:

- **Cache by raw descriptor.** Descriptors repeat heavily, and an LLM call per descriptor on the sync path is a cost/latency change. Memoize extraction results keyed on the exact raw descriptor so each distinct descriptor is resolved once.
- **Structured output.** If the call uses a JSON schema, note the Gemini `additionalProperties` gotcha (AGENTS.md) — the harness strips it, but verify the schema round-trips.
- **This is a rewrite touching callers.** Today `normalize_merchant_name(descriptor) -> str` returns a plain string used purely as a lookup key in the get-or-create merchant logic (`facade.bulk_insert_derived_transactions` and `insert_derived_transaction`), with `display_name` hardcoded to the raw descriptor. The new normalizer returns a richer `NormalizedMerchant`, so those callers must be updated to consume the new fields and populate `source_channel` / `counterparty` on merchant creation. In scope and expected.

#### ATM and other purpose-ambiguous channels

ATM withdrawals (and any channel where the *purpose* of a transaction isn't knowable from the descriptor) normalize to a **single identity per counterparty/location** — e.g. one merchant for `896 MANHATTAN AV`. We deliberately do **not** try to split them by amount band or infer purpose a priori; we have no reliable signal for it. If a user wants `$1,040 ATM withdrawals = nanny pay`, that's expressed as a **user-defined merchant rule**, which is their responsibility — not something the normalizer guesses.

### Validation (replaces backfill)

We are **not** doing an automated backfill that repoints historical `derived_transactions.merchant_id`. Confidence that a bulk repoint does the right thing across the whole history is low, and the cost of getting it wrong (silently mismerging counterparties) is high. Instead, the new normalizer applies **going forward** (new syncs), and we add a **human-in-the-loop validation step** to check the normalizer's quality before trusting it:

1. **Dry-run pass:** run the new LLM normalizer over a broad sample of existing `plaid_transactions` descriptors (no writes). For each, record `descriptor → {normalized_name, display_name, source_channel, counterparty}` and which old `merchant_id`(s) it would collapse/split.
2. **Review HTML page:** generate a static HTML report that walks through each proposed transformation — grouped so related descriptors (e.g. all candidate "Tania Zelle" sends) sit together — with a checkbox per transformation so the reviewer can mark each correct/incorrect and leave notes. This surfaces extraction mistakes (wrong counterparty, dropped identity, over-collapse) before any of it touches real data.
3. **Iterate on the rule repository** based on the checked-off results, then re-run the dry-run. The page is the acceptance gate for the extraction-rule repository, not a migration tool.

Whether (and how) to later repoint historical rows is deferred — once the normalizer is validated as trustworthy, a repoint can be designed as a follow-up with the validation evidence in hand.

**Consequence to be aware of:** with no backfill, existing fragmented/collapsed merchants stay as-is; the cleanup benefit accrues to transactions synced *after* the normalizer ships (plus any future repoint). Flagging this explicitly so it's a known trade-off, not a surprise.

### Expected outcomes

| Before | After |
|---|---|
| Two Tania Zelles → `merchant_id` 2382, 2393 | Both → single merchant `zelle:tania:4352` |
| Future Tania Zelles → new `merchant_id` per send | Same single merchant |
| Rory Mabin Venmo with note "Thank You For Covering" → distinct merchant from any future Venmo with a different note | All Rory Venmos → one merchant `venmo:rory-mabin` |
| ATM withdrawals at `896 MANHATTAN AV` → one merchant (collapse persists; user-defined merchant rules resolve purpose per-pattern, Tier 1 resolves per-row) | Same (intentional — single identity per location) |
| Bambora-as-payment-processor → opaque processor merchant | If sub-merchant present in descriptor → real merchant; else processor as fallback |

(All "After" outcomes apply to transactions synced after the normalizer ships — see the no-backfill consequence above.)

### Verification

- **Evals, not unit tests.** Because extraction is an LLM call driven by natural-language rules, validate it with evals rather than hard-coded unit assertions: a fixture set of real descriptors (from the sampling pass) with expected `{normalized_name, source_channel, counterparty}`, scored as a suite so rule-repository changes can be measured for regression/improvement. Hold out a portion of the corpus as an unseen eval set.
- The **review HTML page** (see *Validation*) is the human acceptance gate before the normalizer is trusted.
- Post-ship query: count `merchants` rows by `source_channel`; sanity-check counts (Zelle merchants should be ~one-per-counterparty going forward).
- Confirm a single `recategorize_merchant` call on a collapsed identity (e.g. `zelle:tania:4352`) recategorizes all of that counterparty's payments synced under the new normalizer.

## Combined payoff

| Problem | Resolved by |
|---|---|
| Need to fix one specific transaction without bulk recategorization | Tier 1 |
| Recurring counterparty (Tania, Rory) gets a new merchant per transaction | Tier 2 |
| `recategorize_merchant` blows away my manual fixes | Tier 1 (verification flag) |
| Payment processor (Bambora) hides the real merchant | Tier 2 |
| Future categorization runs need to respect human-supplied truth | Tier 1 (verification flag → existing `recategorize_merchant` already skips verified rows) |

Tier 1 is the precision instrument; Tier 2 makes precision rarely necessary.

## Out of scope (noted for context)

### Tier 3 — Dedicated overrides table

Considered and **rejected** after discussion. The existing audit log (`transaction_category_events`) plus the `is_verified` flag on `derived_transactions` already supplies override semantics: provenance, reversibility, and protection from bulk operations. A dedicated `transaction_category_overrides` table would duplicate what the audit log already records. Revisit only if a future workload demands single-row override lookups at scale or precedence-stacked overrides from multiple sources.

### Tier 4 — Conditional rule engine with amount/date/account matchers

Today's `merchant-rules.md` is human-readable markdown; the categorizer's interpretation of "amount range" matchers is informal. A first-class structured rule format — YAML in the repo or a `categorization_rules` table — would let rules match on descriptor + amount band + day-of-week + account + reporting mode, write to the audit log with a `method='rule'` flag, and optionally set `is_verified=true` automatically. Useful but additive. Tier 1 + Tier 2 alone resolve most of today's pain; revisit Tier 4 once the merchant graph (Tier 2) is clean enough that rules can target *semantic* merchants instead of raw descriptors.
