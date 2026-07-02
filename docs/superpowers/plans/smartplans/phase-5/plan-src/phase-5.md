---
id: phase-5
label: Phase 5 — Onboarding
parent: roadmap
sections: [goal, scope, security]
crosslinks: [phase-4]
---

# Phase 5 — Onboarding

Guide a new household from empty to productive: banks linked, taxonomy tuned, merchant rules set, first sync done. Builds on signup from phase 4.

Part of the Multi-Account epic — the [overview plan](/p/overview/) is the hub linking all phases.

## Requirements

- A new household can connect its banks and choose what is shared without help.
- Someone can shape their categories and merchant rules during setup rather than discovering them later.
- The first sync clearly shows progress so the household knows the system is working.

## goal — Goal

Turn a freshly created, empty household into one that produces useful answers, through a guided first-run experience.

## scope — Scope

Guided Plaid linking, with per-account visibility chosen at link time, defaulting to private. Taxonomy customization on top of the seeded default. Merchant-rule setup, including rules scoped to a private account. A first-sync experience with progress feedback. A likely dependency: the current Plaid link flow runs a local browser server, so remote onboarding may need the redirect rearchitecture noted in the productionization plan, or ship first for the two local users.

## security — Security focus

Visibility defaults during linking must be private-by-default, opt-in to shared. Plaid token handling at link time must run through the encryption introduced in phase 1a, so a token is never written in the clear.
