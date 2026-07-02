---
id: phase-1b-broker
label: Capability broker
parent: phase-1b
sections: [layout, read-flow, security]
crosslinks: [phase-1b-versioning]
---

# Capability broker

Postgres + RLS decides *where* a household's files live and *which* a given session may read; R2 holds the bytes. You cannot reach a blob without first passing RLS to learn its location.

## layout — Layout & pointers

R2 directories are addressed by **opaque, high-entropy tokens** — never `household_id`, never sequential — so another tenant's prefix cannot be guessed. Layout partitions by visibility: **one shared prefix per household** and **one private prefix per user**. Postgres holds pointer rows (R2 token, `owner_user_id`, `household_id`, `visibility`) under the same RLS policy as the financial tables.

## read-flow — Read flow

The app derives an R2 key **only** from an RLS-gated Postgres lookup — never from user or agent input. The lookup returns **only the prefixes the current principal + session mode may read**, so filtering happens before any R2 fetch:

- **Individual session** → the user's private prefix + the household shared prefix.
- **Joint session** → the shared prefix **only**; private prefixes are never resolved, so those bytes never reach the temp dir.

Allowed blobs are synced into a per-run temp dir, torn down after the run and excluded from logs.

## security — Security posture

RLS protects the *pointer*, not the *bytes* — a notch weaker than pure-Postgres storage, mitigated to safe by: opaque tokens, R2 credentials that cannot `LIST` the bucket, keys derived only from RLS-gated lookups, and **no direct agent access to R2** (only the workspace shim touches it). This access path is an explicit phase-6 audit item. Write-back and its atomicity are covered in [versioning and CAS](versioning.html).
