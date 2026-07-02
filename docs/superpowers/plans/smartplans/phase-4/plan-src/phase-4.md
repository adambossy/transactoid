---
id: phase-4
label: Phase 4 — Signup UI
parent: roadmap
sections: [goal, scope, security]
crosslinks: [phase-2, phase-5]
---

# Phase 4 — Signup UI

Let an invited user create an account and bootstrap a household through the UI instead of being provisioned by hand.

Part of the Multi-Account epic — the [overview plan](/p/overview/) is the hub linking all phases.

## Requirements

- An invited person can create their account and land in a working, isolated household without an engineer setting it up.
- A second person can join an existing household rather than starting a new one.
- A brand-new household starts fully isolated, with its taxonomy ready to use.

## goal — Goal

Make account creation self-serve, still gated to invited people, so growth past the first two users does not require manual database work.

## scope — Scope

A signup flow gated to invited emails. Household bootstrap on first signup: create the household, seed the taxonomy from the default, and create the user's private workspace prefix. A way to join an existing household versus creating a new one — which is where the one-household-per-user simplification may need to relax toward membership. The frontend account-creation screens.

## security — Security focus

Account creation is a near-unauthenticated entry point: enforce the invite allow-list, resist abuse, and ensure a freshly created household is completely isolated from the moment it exists. Onboarding picks up from here in phase 5.
