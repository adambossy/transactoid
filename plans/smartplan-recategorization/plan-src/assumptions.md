---
id: assumptions
label: Assumptions & open questions
parent: root
sections: [asked, assumed, open]
crosslinks: [tier-2-validation]
---

# Assumptions & open questions

This SmartPlan was generated from the source plan dated 2026-06-11. What was given, what was assumed in turning it into a tree, and what remains open.

## asked — What the source plan settled

| Question | Decision in the source plan |
| --- | --- |
| Scope | Tier 1 and Tier 2 only; Tier 3 and Tier 4 noted for context, not in scope |
| Backfill | No automated historical repoint; apply going forward, gate with a review page |
| Extraction approach | LLM call over a versioned rule repository, not per-vendor matchers |
| Purpose-ambiguous channels (ATM) | Single identity per counterparty/location; purpose handled by user rules or Tier 1 |

## assumed — What I assumed turning it into a tree

| Assumption | Why |
| --- | --- |
| Tier 2 split into sampling / normalizer / validation sub-pages | The source plan has three distinct phases; one page each keeps every page a quick read |
| Two Mermaid diagrams (failure modes, normalizer flow) | The two ideas are clearer as pictures than prose |
| The problem and payoff get their own top-level pages | They frame and close the plan; readers should be able to land on either directly |

## open — Open questions

- **When and how to repoint history.** Deferred by design — but it depends on the [validation](tier-2/validation.html) evidence, and the design of a safe repoint is unspecified.
- **Eval acceptance bar.** The plan calls for eval scoring of the normalizer but does not fix a passing threshold or the size of the held-out set.
- **Cache invalidation.** Memoizing by raw descriptor is specified; how/whether the cache is invalidated when the rule repository changes is not.
- **Cost/latency budget.** The LLM normalizer is acknowledged as a cost/latency change on the sync path, but no target budget is stated.
