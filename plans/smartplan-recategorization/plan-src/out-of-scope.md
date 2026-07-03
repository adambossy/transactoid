---
id: out-of-scope
label: Out of scope
parent: root
sections: [tier-3, tier-4]
crosslinks: []
---

# Out of scope

Two tiers were considered and deliberately left out of this plan, recorded so the boundary is explicit.

## tier-3 — Tier 3: dedicated overrides table

Considered and **rejected**. The existing audit log (`transaction_category_events`) plus the `is_verified` flag already supply override semantics: provenance, reversibility, and protection from bulk operations. A dedicated `transaction_category_overrides` table would duplicate what the audit log records. Revisit only if a future workload demands single-row override lookups at scale, or precedence-stacked overrides from multiple sources.

## tier-4 — Tier 4: conditional rule engine

A first-class structured rule format — YAML in the repo or a `categorization_rules` table — would let rules match on descriptor + amount band + day-of-week + account + reporting mode, write to the audit log with `method='rule'`, and optionally set `is_verified=true` automatically. Useful but additive. Tier 1 + Tier 2 resolve most of today's pain; revisit Tier 4 once the merchant graph is clean enough that rules can target *semantic* merchants instead of raw descriptors.
