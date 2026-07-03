---
id: tier-1
label: Tier 1 — Per-transaction recategorize
parent: root
sections: [goal, the-tool, reuse-and-protection, verification]
crosslinks: [problem, payoff]
---

# Tier 1 — Per-transaction recategorize

Close today's tooling gap so an individual transaction can be recategorized cleanly, without bypassing the no-raw-write-SQL guardrail. No schema changes — the data model already supports per-row category mutation.

## Requirements

- A user can correct the category of a single transaction without touching any other transaction.
- Every manual correction is recorded with provenance — who/what changed it, from which category to which.
- A manual fix is protected from being overwritten by a later bulk recategorization.
- The fix happens through a supported tool, never through raw write SQL.

## goal — Goal and scope

`derived_transactions` already carries `category_id`, `category_method`, `category_assigned_at`, and `is_verified`, and `transaction_category_events` already records transitions. So Tier 1 is purely a tooling addition: expose a clean per-row recategorize on the MCP surface. Effort is hours, not days — roughly a 30-line tool body plus a thin MCP wrapper.

## the-tool — The new MCP tool

```python
recategorize_transaction(
    transaction_id: int,
    category_key: str,
    reason: str | None = None,
    verify: bool = True,
) -> {updated: bool, event_id: int}
```

It resolves `category_key` to `category_id` via `categories.key`, filtered on the active partial unique index (`deprecated_at IS NULL`) so deprecated or unknown keys are rejected. It then updates the row — `category_id` to the new id, `category_method='manual'`, `category_model=NULL`, `category_assigned_at=NOW()`, `is_verified=TRUE` when `verify=True` — and inserts a `transaction_category_events` row with `method='manual'`, the from/to categories, and the optional reason.

## reuse-and-protection — Reuse and protection

The atomic update-plus-event logic already exists in the façade as `_apply_category_updates(...)`. Reuse it, but **replace** its `reset_verified` flag with `is_verified: bool | None = None`: `True`/`False` set the column, `None` leaves it untouched. Existing callers that passed `reset_verified=True` pass `is_verified=False`.

Because the tool sets `is_verified=true` by default, and `recategorize_merchant` already skips verified rows, **manual fixes are automatically protected from future bulk operations** — no new locking primitive needed. The provenance CHECK constraint covers only `(category_id, category_method, category_assigned_at)`, so setting `category_model=NULL` alongside them is constraint-safe.

## verification — Verification

- Smoke test: recategorize a known row; confirm the row updated, the audit event written, and a subsequent `recategorize_merchant` for that merchant skips the row.
- Round-trip: recategorize a row twice; confirm two audit events with the correct from/to chain.

See the [combined payoff](../payoff/index.html) for how Tier 1 and Tier 2 divide the work.
