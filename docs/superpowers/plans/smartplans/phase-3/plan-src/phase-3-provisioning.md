---
id: phase-3-provisioning
label: Provisioning runbook
parent: phase-3
sections: [rehearse, steps]
crosslinks: [phase-3-admin, phase-3-acceptance]
---

# Provisioning runbook

Operator-executed. Uses the [admin CLI](admin-cli.html). Rehearse the entire sequence against the `penny-test` branch first, then repeat against prod.

## rehearse — Rehearse, then execute

Run the backend locally against the target DB (`.env.test` for the test branch; the prod env for prod) with `PENNY_AUTH_MODE=clerk` and Clerk dev keys. Because the admin CLI is idempotent, the same steps run cleanly on both environments — the test-branch pass is a full dress rehearsal, and only after acceptance passes there do you touch prod.

## steps — Steps

1. `penny admin create-household --name "<household>"` → note household id `H`.
2. `penny admin create-user --household H --email you@example.com` → `U1`.
3. `penny admin create-user --household H --email wife@example.com` → `U2`.
4. Add both emails to the Clerk allowlist.
5. Each spouse signs in locally via Clerk once → confirm `users.external_auth_id` is populated for both (phase-2 first-login linking).
6. Confirm the phase-1a backfill assigned existing data to `H` / `U1` / `private` (spot-check `list-accounts --household H --admin-user U1`).
7. Each spouse links their own banks via the local Plaid Link flow.
8. `list-accounts` for each member to review owners + visibility.
9. `set-account-visibility --visibility shared …` for each account you intend to share; re-list to confirm.

Then run the [acceptance checklist](acceptance.html) — on the test branch first, prod second.
