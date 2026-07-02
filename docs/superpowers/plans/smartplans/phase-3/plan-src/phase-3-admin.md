---
id: phase-3-admin
label: Admin CLI
parent: phase-3
sections: [commands, idempotency, rls-context]
crosslinks: [phase-3-provisioning]
---

# Admin CLI

A `penny admin` Typer command group (in `penny/admin.py`, kept separate from the user-facing `run` commands) — the one code deliverable of phase 3. Never exposed over HTTP; a local maintenance tool only.

## commands — The commands

- `create-household --name` → creates/returns a household row.
- `create-user --household <id> --email` → creates a user row (lowercased email); `external_auth_id` stays null until first Clerk login links it (phase 2).
- `list-accounts --household <id> --admin-user <id>` → lists `plaid_accounts` with owner email + visibility, so you can see what to flip.
- `set-account-visibility --account <id> --visibility private|shared --owner <id> --household <id>` → flips the `plaid_accounts` row **and** the denormalized `visibility` on that account's transactions, in one transaction.

## idempotency — Idempotency

Every command is safe to re-run: `create-household` returns the existing id for an existing name; `create-user` returns the existing id for an existing (lowercased) email; visibility flips are naturally idempotent. Re-running the whole provisioning sequence never duplicates rows — which is what lets you rehearse on the test branch and repeat on prod without fear.

## rls-context — RLS context

`households` and `users` are the identity registry and are not RLS-scoped, so those inserts are direct. `plaid_accounts` **is** RLS-scoped, so `list-accounts` and `set-account-visibility` run under an explicit `RequestContext` (`--admin-user` / `--owner` set the household + user), acting as a member of the household. To see another member's accounts, run under that member's id. Used by the [provisioning runbook](provisioning.html).
