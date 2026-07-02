---
id: phase-3
label: Phase 3 — Provision + test
parent: ""
sections: [goal, decisions, deliverable]
crosslinks: [phase-3-admin, phase-3-provisioning, phase-3-acceptance]
---

# Phase 3 — Provision + test

Part of the Multi-Account epic — the [overview plan](/p/overview/) is the hub linking all phases.

Stand up the two real users in one household and validate the whole multi-tenant + auth stack against real financial data — the first time real money data flows through the isolated path. Mostly a runbook plus an acceptance definition, with one real code deliverable: an idempotent admin CLI.

## Requirements

- Both spouses can log in and see the right combined-and-private picture of their real finances.
- The existing real data ends up correctly assigned, with only the intended accounts shared.
- A pass over real data shows no household can see another, and no spouse can see the other's private accounts.

## goal — Goal

Prove the system end to end with real money data before opening it more widely, using the isolation built in phases 1a/1b/2 — no new mechanism.

## decisions — Locked decisions

Provision via an **idempotent admin CLI** (reusing phase 1a's `backfill_household` helper). Run the backend **locally** so Plaid Link's localhost flow works, against the Neon **`penny-test` branch first (rehearse), then prod (execute)**. Validate cross-household isolation with phase 1a's automated two-household suite (synthetic A/B); use **real data** for within-household privacy and joint checks.

## deliverable — Structure

The [admin CLI](admin-cli.html) is the code; the [provisioning runbook](provisioning.html) and [acceptance checklist](acceptance.html) are operator-executed.

```mermaid
flowchart LR
  cli[Admin CLI] --> prov[Provision on test]
  prov --> acc[Acceptance on test]
  acc --> prod[Repeat on prod]
```
