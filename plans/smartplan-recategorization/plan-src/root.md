---
id: root
label: Executive summary
parent: ""
sections: [the-goal, the-two-tiers, key-tradeoffs]
crosslinks: [problem, tier-1, tier-2]
---

# Individual Recategorization & Smarter Merchant Normalization

Two complementary changes to the categorization pipeline: a precision instrument for fixing one transaction at a time, and a root-cause fix that makes the merchant graph carry real meaning. Tier 1 and Tier 2 are in scope; Tier 3 and Tier 4 are noted for context only.

## the-goal — The goal

Today `merchant_id` is overloaded as both the *identity* of a counterparty and the *handle* for bulk recategorization. That breaks on wrapper descriptors — Zelle, Venmo, ATM, payment processors — in two opposite ways, and there is no clean way to fix a single transaction without raw write SQL, which the project forbids. The goal is to close the per-transaction gap and to make merchant identity mean "who," not "whatever message Plaid happened to send."

## the-two-tiers — The two tiers

**Tier 1 — a per-transaction recategorize tool.** A new MCP tool, `recategorize_transaction`, that updates one row and writes an audit event, reusing logic that already exists in the DB façade. See [Tier 1](tier-1/index.html).

**Tier 2 — smarter merchant normalization.** Teach the normalizer about wrapper descriptors via an LLM call driven by a versioned repository of extraction rules, so recurring counterparties collapse to one merchant. Validated by a human-in-the-loop review, applied going forward — no risky historical backfill. See [Tier 2](tier-2/index.html).

Tier 1 is the precision instrument; Tier 2 makes precision rarely necessary.

## key-tradeoffs — Key tradeoffs

The biggest deliberate choice is **no automated backfill**: confidence that a bulk repoint of historical `merchant_id`s does the right thing is low, and the cost of silently mismerging counterparties is high. The normalizer applies to new syncs only, gated by a review page; repointing history is deferred until the normalizer is proven. The second is **LLM extraction over hand-written matchers** — per-vendor regex doesn't scale to the long tail of wrappers, so identity extraction is natural-language rules the model interprets, validated with evals. See [the problem](problem/index.html) for why both are needed.
