---
id: phase-1a-testing
label: Testing
parent: phase-1a
sections: [postgres-marker, suites, acceptance]
crosslinks: [phase-1a-enforcement]
---

# Testing

Multi-tenancy lives or dies in the tests. The challenge: the RLS guarantees from the [enforcement page](enforcement.html) cannot be proven on SQLite, which the existing fast test suite uses.

## postgres-marker — The Postgres path

RLS tests carry a marker and run against a real Postgres database — the Neon test branch or a local instance — selected by an environment variable. When that variable is unset, those tests skip, so the everyday SQLite suite stays fast. Each test seeds two households in their own schema and tears it down afterward.

## suites — The suites

Three behavioral suites assert the spec's guarantees. A **cross-household leakage** suite seeds households A and B and asserts that queries from A — including raw `run_sql` — return zero B rows. A **within-household privacy** suite asserts a spouse's private account is invisible to the other while a shared account is visible to both. A **joint-session** suite asserts a joint run sees shared-only across transactions, memories, and reports.

## acceptance — Acceptance battery

A consolidated battery pins the end state with explicit assertions: own-private-plus-shared in individual mode, shared-only in joint mode, a private account hidden from a spouse, a shared account visible to both, and a write rejected when it targets a foreign household. Green here, plus a clean ruff and full pytest run, is the bar for phase 1a being done.
