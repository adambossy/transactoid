---
id: payoff
label: Combined payoff
parent: root
sections: [resolution-table, precision-vs-prevention]
crosslinks: [tier-1, tier-2]
---

# Combined payoff

How the two tiers divide the work, and why both are worth doing.

## resolution-table — What each tier resolves

| Problem | Resolved by |
| --- | --- |
| Fix one specific transaction without bulk recategorization | Tier 1 |
| Recurring counterparty (Tania, Rory) gets a new merchant per transaction | Tier 2 |
| `recategorize_merchant` blows away my manual fixes | Tier 1 (the verification flag) |
| Payment processor (Bambora) hides the real merchant | Tier 2 |
| Future categorization runs must respect human-supplied truth | Tier 1 (verified rows are skipped by the bulk tool) |

## precision-vs-prevention — Precision vs. prevention

[Tier 1](../tier-1/index.html) is the precision instrument: it fixes any single row cleanly and protects that fix. [Tier 2](../tier-2/index.html) is prevention: by making merchant identity mean "who," it removes most of the situations that would otherwise need a per-row fix, and restores `recategorize_merchant` as a useful bulk tool against *semantic* merchants. Tier 1 makes Tier 2's residual mistakes cheap to correct; Tier 2 makes Tier 1 rarely necessary.
