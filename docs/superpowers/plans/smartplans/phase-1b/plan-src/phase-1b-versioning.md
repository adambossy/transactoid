---
id: phase-1b-versioning
label: Versioning & CAS
parent: phase-1b
sections: [manifests, commit-cas, write-back, tests]
crosslinks: [phase-1b-broker]
---

# Versioning & CAS

The mental model: **temp dir = working tree, R2 = object store, a Postgres manifest = the commit.** The read side is in the [capability broker](broker.html).

## manifests — Manifests over immutable blobs

R2 holds content as immutable, content-addressed blobs. Postgres holds an append-only **manifest** row per save: the set of blobs making up that point-in-time snapshot, under the same RLS policy. The manifest is the source of truth for "current version"; rollback is pointing the head at an older manifest. **Refinement from the implementation plan:** heads are per-*prefix* (shared, private-per-user), not one per household — a household-wide head cannot survive RLS, because a joint run's flush would have to copy forward private entries it cannot read. Per-prefix chains keep every guarantee; a joint run only ever holds the shared head.

## commit-cas — Commit boundary & atomic CAS

The agent edits the temp dir freely during a run (many edits, zero R2/Postgres traffic per edit). Versioning happens at the **run boundary**: one manifest per run. The flush uploads changed blobs **first** (immutable, side-effect-free — orphans from a losing race are harmless), then performs the single mutating step: a **compare-and-set** on the household workspace head — advance it *iff* it still equals the parent we materialized from. If the CAS fails, the head moved: re-materialize the new head, re-apply the diff (memory/rules are append-ish markdown that merges cleanly), and retry. The only state change is the atomic CAS, so there is never a half-applied commit.

```mermaid
flowchart TD
  edits[Agent edits temp dir] --> flush[Flush at run boundary]
  flush --> blobs[Upload changed blobs to R2]
  blobs --> cas{CAS: head == parent}
  cas -- yes --> commit[Insert manifest, advance head]
  cas -- no --> remat[Re-materialize head, re-apply, retry]
  remat --> cas
```

## write-back — Visibility-routed write-back

Each changed file flushes back to the prefix it came from — shared to the shared prefix, private to the owner's private prefix. A **joint session only ever materialized shared files, so it can only write shared** — private data cannot leak outward even on write. New files default to **private** in an individual session (promotable later) and **shared** in a joint one (the only scope available).

## tests — Test suite

Postgres-marked: (a) a joint session never resolves a private prefix — private bytes never reach the temp dir; (b) concurrent flushes off the same parent — one CAS wins, the loser re-materializes and retries, no lost update; (c) an aborted run commits nothing.
