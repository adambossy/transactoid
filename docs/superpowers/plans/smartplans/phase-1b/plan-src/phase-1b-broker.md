---
id: phase-1b-broker
label: Capability broker
parent: phase-1b
sections: [layout, read-flow, security]
crosslinks: [phase-1b-versioning]
---

# Capability broker

Postgres + RLS decides *where* a household's files live and *which* a given session may read; R2 holds the bytes. You cannot reach a blob without first passing RLS to learn its location.

## Requirements

- A household's files can only be reached after the system confirms the requester is allowed to see them; their location is never guessable.
- In a shared conversation, private files are never located or fetched, so private content cannot leak outward.
- One household can never stumble onto another household's files, even by guessing.

## layout — Layout & pointers

R2 directories are addressed by **opaque, high-entropy tokens** (`secrets.token_urlsafe`) — never `household_id`, never sequential — so another tenant's prefix cannot be guessed. Layout partitions by visibility: **one shared prefix per household** and **one private prefix per user**, each tagged with a `kind` and `visibility`. Postgres holds pointer rows (R2 token, `owner_user_id`, `household_id`, `visibility`) under the same RLS policy as the financial tables, with partial unique indexes enforcing the one-shared-per-household and one-private-per-user shape. Prefixes are minted **lazily** the first time a principal needs them, so no provisioning step precedes a run.

## read-flow — Read flow

The app derives an R2 key **only** from an RLS-gated Postgres lookup — never from user or agent input. The lookup returns **only the prefixes the current principal + session mode may read**, so filtering happens before any R2 fetch:

- **Individual session** → the user's private prefix + the household shared prefix.
- **Joint session** → the shared prefix **only**; private prefixes are never resolved, so those bytes never reach the temp dir.

The readable set is resolved **shared first, private overlaying**, so a private file wins a path collision with a shared one. Allowed blobs are synced into a per-run temp dir, torn down after the run and excluded from logs.

## security — Security posture

RLS protects the *pointer*, not the *bytes* — a notch weaker than pure-Postgres storage, mitigated to safe by: opaque tokens, R2 credentials that cannot `LIST` the bucket, keys derived only from RLS-gated lookups, and **no direct agent access to R2** (only the workspace shim touches it). This access path is an explicit phase-6 audit item. Write-back and its atomicity are covered in [versioning and CAS](versioning.html).
