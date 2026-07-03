---
id: phase-4-testing
label: Security & testing
parent: phase-4
sections: [abuse-surface, tests, future-work]
crosslinks: [phase-4-invites]
---

# Security & testing

## abuse-surface — The open-signup abuse surface

Fully open signup on a bank-linking app means anyone can create accounts and initiate Plaid links — a cost and abuse surface. Mitigations to add and track: rate-limit signup and Plaid-link initiation per identity/IP, and monitor Plaid usage. Flagged as an explicit phase-6 audit item. Isolation itself is not at risk: two independent signups yield two fully isolated households under phase-1a RLS, and re-linking the same bank in two households produces independent Plaid items with no shared rows.

## tests — Test surface

Postgres-marked where RLS is involved: a new verified user gets a solo household with seeded taxonomy; two independent signups are mutually invisible (leakage probe via raw SQL from each context); an invited email lands in the inviter's household, not a new one; inviting an already-active email returns 409; a revoked invite no longer links on signup; concurrent first-login requests provision exactly one household; the same bank linked from two households yields independent items.

## future-work — Recorded future work

**Solo-household re-parent on join:** allow inviting an existing user *only if* their household is solo — on accept, re-parent their accounts and transactions into the inviter's household (update the tenant key, remap categories by key) and retire the empty solo household. Preserves legacy data without household merge or many-to-many membership. Revisit if "new users only" proves limiting.
