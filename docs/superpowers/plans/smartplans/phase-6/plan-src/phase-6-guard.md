---
id: phase-6-guard
label: CI regression guard
parent: phase-6
sections: [policy-lint, suites, e2e, dep-scan]
crosslinks: [phase-6-matrix, phase-6-deliverables]
---

# CI regression guard

The audit's guarantees become permanent. The accumulated isolation suites, a policy linter, adversarial browser tests, and a dependency scan are promoted into a required CI job that runs on every change. A red run means isolation regressed and the merge is blocked — so the invariants proven once cannot silently break later.

## Requirements

- Every proposed change is checked against the full isolation test surface before it can merge, with no way to skip the gate.
- A deliberately weakened isolation policy turns the gate red, proving the guard actually catches regressions.
- The owner can trust that a green build means cross-household and cross-spouse isolation still holds.

## policy-lint — RLS policy-lint

A durable linter asserts that every tenant table has row-level security fully covered — both a read clause and a write-check clause on its isolation policy, plus forced row-level security — by introspecting the database's own policy catalog. It carries no hard-coded knowledge of the schema: the table set is passed in or discovered from the catalog, so the linter lifts cleanly into any isolation-based multi-tenant Postgres app. It returns human-readable violations and exits non-zero for CI. A companion test proves a clean schema yields no violations and that disabling a policy is detected.

## suites — Postgres isolation suites

The Postgres-marked suites accumulated across earlier phases run against the Neon test branch: cross-household leakage, within-household privacy, joint-session and workspace isolation from phases 1a and 1b; the auth 401 / 403 / direct-object-reference battery and conversation scoping from phase 2; signup isolation from phase 4; and the reminder end-to-end check from phase 5, proving a reminder reaches the model's turn but never the stored transcript. Every verified finding from the audit ships its own regression test that joins this set.

## e2e — Adversarial browser E2E

Headless Playwright specs reuse the phase-1a harness and the test-user sign-in helper to attack the real app through the UI and URLs. A cross-user case signs in as one user and confirms another user's private conversation URL is blocked and never rendered. A cross-household case confirms a user cannot reach another household's transactions, reports, or workspace through any screen or deep link. A signed-out case confirms protected routes gate to sign-in with no financial data flashing before auth. An abuse case confirms repeated signup or link-token requests hit the rate limit and show the shared-template error state. Any real failure here is itself a finding fed back to the [coverage matrix](matrix.html).

## dep-scan — Dependency scan

A supply-chain scan runs on every build across both the Python and JavaScript dependency trees, flagging known vulnerabilities and confirming versions stay pinned. Together with the linter, the isolation suites, and the browser specs, it composes a can't-silently-break merge gate whose green result feeds the go-live [deliverables](deliverables.html).
