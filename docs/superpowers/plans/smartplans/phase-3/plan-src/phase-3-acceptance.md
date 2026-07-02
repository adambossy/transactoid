---
id: phase-3-acceptance
label: Acceptance checklist
parent: phase-3
sections: [automated, real-data, secrets]
crosslinks: [phase-3-provisioning]
---

# Acceptance checklist

What proves "no leakage." Record outcomes as a completion artifact (paste the `run_sql` probe results). Run on `penny-test` first; only after all pass, repeat on prod.

## automated — Automated suites

The phase-1a/1b/2 Postgres-marked suites are green against the prod-equivalent config: cross-household leakage (synthetic households A/B), within-household privacy, joint, workspace, and auth suites all pass. This is the cross-tenant proof — real data need not be exposed to a second real household.

## real-data — Real-data checks

- **Within-household privacy:** logged in as `U1` (individual), the UI and a `run_sql` count over `derived_transactions` exclude `U2`'s private accounts; repeat as `U2`.
- **Joint session:** a joint conversation returns shared-only — neither spouse's private transactions, memories, or reports appear.
- **Conversation isolation:** `U1` cannot open `U2`'s individual conversation (403/404); a joint thread is visible to both.
- **Cron:** each per-user report is correctly scoped and reaches only that user; the household shared report is shared-only and reaches both.
- **Workspace:** a real agent run materializes, writes back, and versions; a joint run never resolves a private prefix.

## secrets — Secrets

`SELECT access_token FROM plaid_items LIMIT 1` returns ciphertext; a log grep confirms no plaintext token. Only when every box passes on the test branch do you repeat provisioning and this checklist against prod.
