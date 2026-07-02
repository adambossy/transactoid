---
id: phase-6
label: Phase 6 — Security audit
parent: roadmap
sections: [goal, focus-items, output]
crosslinks: [phase-1a-testing, workspace-storage]
---

# Phase 6 — Security audit

Intensely audit the whole system so personal financial data cannot leak across households or between spouses, before and while real data is in use.

Part of the Multi-Account epic — the [overview plan](/p/overview/) is the hub linking all phases.

## Requirements

- An independent, adversarial pass finds no way for one household to read another's data.
- No way is found for a spouse to read the other's private accounts, including by coaxing the agent.
- Bank tokens and other secrets are confirmed safe at rest, in transit, and in logs.

## goal — Goal

Produce a severity-tiered findings report and remediation plan that justifies trusting the product with real money data at scale.

## focus-items — Focus items

Cross-tenant leakage across every façade method and a battery of `run_sql` queries. An RLS policy audit confirming every table has the right policy and the denormalized columns stay consistent. The R2 access path, since RLS protects the pointer but not the bytes — verify opaque tokens, non-listing credentials, keys derived only from RLS lookups, and no direct agent access to R2. The workspace concurrency model from the storage decision: CAS atomicity, no lost updates, temp-dir hygiene. Secret handling and prompt-injection attempts against the agent's tools, which the testing suites begin but do not exhaust.

## output — Output

A written report with severity tiers, a clear split of blocking versus tracked-for-later findings, and a decision on whether to engage an external reviewer given the sensitivity of the data.
