# Multi-Account Support — Design

**Status:** Approved design (sub-project 1 detailed; phases 2–6 roadmap)
**Date:** 2026-06-27
**Branch:** `feat/account-creation`

## Goal

Turn Penny from a single-user app into a multi-tenant one that you and your
wife can both use, with bank-grade isolation of personal financial data. The
work is sequenced as six sub-projects; **this spec details sub-project 1 (the
multi-tenant data model)** and sketches the rest as a roadmap. Each later
sub-project will get its own spec → plan → build cycle.

## Sub-project sequence

1. **Multi-tenant data model + code** (this spec) — tenancy, RLS, query scoping.
2. **Auth / social login** — Clerk or Auth0, Google sign-in, you + wife only.
3. **Provision the two accounts + test** end to end.
4. **Signup / account-creation UI.**
5. **Onboarding** — Plaid linking, taxonomy setup, merchant rules.
6. **Security audit** — adversarial review focused on cross-tenant leakage.

Security is a first-class concern at every step, not a final phase; sub-project
6 is a dedicated audit, but each phase carries its own security work (e.g.
Plaid-token encryption lands in phase 1).

---

# Sub-project 1: Multi-tenant data model

## Decisions (locked)

- **Tenant unit:** a **household**. A household groups one or more users and is
  the grouping for shared finances.
- **Hard isolation boundary:** **user-centric RLS**. The database enforces, on
  every query, both cross-household isolation *and* within-household privacy.
- **Sharing granularity:** **per Plaid account**. Each account is owned by a
  user and is `private` or `shared`. This revives a `plaid_accounts` table
  (dropped in an earlier migration).
- **Enforcement:** **Postgres RLS (hard backstop) + app-level filtering
  (belt-and-suspenders).** App filtering keeps SQLite local dev correct and
  intent legible; RLS is the guarantee, including over the agent's `run_sql`.
- **Reversibility:** we start **strict** (user-centric). Loosening later
  (→ household-only) is a one-line policy change; tightening later would be a
  risky backfill+window, so strict-first is the safe direction.
- **Taxonomy:** **per-household**, seeded from `configs/taxonomy.yaml` at
  household creation; customizable thereafter. Per-household, *not* per-user.
- **Merchant normalization:** **global** (coordinate with WIP on
  `feat/individual-recategorization`).
- **Merchant rules:** **per-household**; a rule targeting a private account
  inherits that account's privacy.
- **Joint agent sessions:** the agent can run in *individual* or *joint* mode;
  joint mode sees **shared-only** data — no private data of either spouse leaks
  into a shared run.
- **Workspace storage:** **hybrid — Postgres+RLS as capability broker, R2 as blob
  store.** Versioned via Postgres manifests over immutable R2 object versions;
  writes committed at the run boundary with **atomic optimistic concurrency**
  (compare-and-set on the workspace head).

## Domain model

**New identity tables:**

- `households` — `(household_id PK, name, created_at)`. The tenant.
- `users` — `(user_id PK, household_id FK, email, external_auth_id, created_at)`.
  `external_auth_id` is the Clerk/Auth0 subject, null until phase 2. A user
  belongs to **exactly one** household for now (multi-household membership is
  YAGNI; the FK can become a join table later without re-migrating financial
  tables).

**Revived table:**

- `plaid_accounts` — `(account_id PK, item_id FK→plaid_items, owner_user_id
  FK→users, household_id, visibility ENUM('private','shared'), …)`. The source
  of truth for per-account ownership and sharing. `account_sign_conventions`
  already keys on `account_id` and slots in here.

**Ownership chain:**

- `plaid_items.owner_user_id` — a link is owned by whoever connected it.
- `plaid_accounts.owner_user_id` + `visibility` — per-account sharing control.
- A transaction has **no flag of its own**; its visibility is *derived* from its
  account (and denormalized for policy speed — see below).

**`visibility` semantics:**

- `private` — only the owning user sees the account and its transactions; hidden
  from everyone else, *including the spouse in the same household*.
- `shared` — visible to the whole household.
- The owner sets it. It makes "share my Chase checking, hide my Chase savings"
  work.

## Enforcement mechanics

**Request principal.** Every request resolves to
`RequestContext { user_id, household_id, session_mode }` where `session_mode ∈
{individual, joint}`. In phase 1 (pre-auth) this comes from a **dev stub** (a
configured header like `X-Penny-User`, or an env-pinned user) so multi-tenancy
is runnable and testable before Clerk exists. Phase 2 swaps the stub for real
auth; nothing downstream changes because everything reads `RequestContext`.

**Setting the boundary on the connection.** At the start of each request/agent
run, the façade's session context manager issues (transaction-scoped, so it
cannot leak across pooled connections):

```sql
SET LOCAL app.current_household = :household_id;
SET LOCAL app.current_user      = :user_id;   -- nil-UUID sentinel in joint mode
```

**RLS policy** on every per-household table that carries ownership:

```sql
USING (
  household_id = current_setting('app.current_household')::uuid
  AND (owner_user_id = current_setting('app.current_user')::uuid
       OR visibility = 'shared')
)
```

- **Individual session:** `current_user` is the real user → own-private + shared.
- **Joint session:** `current_user` is a nil sentinel → the owner arm never
  matches → **shared-only**. One policy covers both modes.
- Tables without ownership (e.g. `categories`, `tags`) carry only the
  `household_id` term.

**Denormalized columns.** To keep the policy join-free and fast, every
transaction-scoped table carries `household_id`, `owner_user_id`, and (where
relevant) `visibility`, written from `plaid_accounts` at insert time. A
`visibility` change updates `plaid_accounts` and the denormalized copies in one
transaction.

**App-level filtering (suspenders).** The façade still adds
`WHERE household_id = ctx.household` (and visibility terms) on its ~50 methods.
This keeps SQLite dev correct (no RLS there) and makes intent legible; RLS is the
backstop when a query forgets.

**`run_sql`.** Because RLS binds to the connection, the agent's unrestricted
`run_sql` is automatically scoped and physically cannot read another household's
or a member's private rows. No change to the tool itself — only that it runs on
an RLS-governed connection with the settings applied.

## Reference-data scoping

| Scope | Tables |
|---|---|
| **Global** (no household_id, no RLS) | `merchants` (normalization) |
| **Per-household, household-term only** | `categories`, `tags`, `transaction_category_events`, conversations (web schema) |
| **Per-household + owner/visibility** | `plaid_items`, `plaid_accounts`, `plaid_transactions`, `derived_transactions`, `transaction_items`, `transaction_tags`, `email_receipts`, `pending_receipt_matches`, `account_sign_conventions`, `amazon_login_profiles` / `amazon_orders` / `amazon_items` |

## Workspace / memory partitioning

Today the workspace is `~/.transactoid` (itself a standalone git repo for
versioning). In a multi-tenant, remote-deployable world (Fly's filesystem is
ephemeral) this becomes a **hybrid: Postgres+RLS as the capability broker, R2 as
the blob store.** The durable source of truth is split — Postgres holds the
authorization + version graph, R2 holds the bytes.

**Mental model:** *temp dir = working tree, R2 = object store, Postgres manifest
= the commit.*

### Layout & lookup

- R2 directories are addressed by **opaque high-entropy tokens**, never by
  `household_id` and never sequential — you cannot guess another tenant's prefix.
- Layout partitions **by visibility**: one **shared prefix per household** and
  one **private prefix per user**.
- Postgres holds pointer rows (R2 token, `visibility`, `owner_user_id`,
  `household_id`) under the **same RLS policy** as the financial tables. The
  app derives an R2 key **only** from an RLS-gated lookup — never from user/agent
  input.
- The lookup returns **only the prefixes the current principal + `session_mode`
  may read**, so filtering happens *before* any R2 fetch:
  - **Individual session:** the user's private prefix + the household shared
    prefix.
  - **Joint session:** the shared prefix **only** — private prefixes are never
    resolved, so those bytes never reach the temp dir.
- R2 credentials are scoped so the app cannot `LIST` the bucket arbitrarily, and
  **the agent has no direct R2 capability** — only the workspace shim does.

### Read flow

RLS-gated Postgres read → returns allowed prefix(es) + current manifest → sync
those R2 object versions to a **per-run temp dir** (torn down after the run,
never shared across sessions/households, excluded from logs) → agent runs.

### Write flow, versioning & atomicity

The agent mutates the temp dir freely and repeatedly during a run (local-FS
speed, **zero R2/Postgres traffic per edit**). Versioning happens at a
**boundary, not per file-write**:

- **Default boundary: one manifest per run** (≈ one commit per agent turn). At
  run completion the flush diffs the temp dir against the baseline manifest,
  uploads only changed/new blobs as new **immutable R2 object versions**, and
  inserts **one** manifest row recording the set of object versions for that
  snapshot. Nothing changed → no empty commit.
- **Crash semantics:** an aborted run commits nothing — no partial/incoherent
  memory edits pollute the workspace. (Optional later enhancement: mid-run
  checkpoint manifests for long runs; not in v1.)
- **Atomic optimistic concurrency** (chosen strategy): each manifest records its
  **parent**. The commit is a single conditional transaction — *insert the new
  manifest row and advance the workspace head iff the head still equals the
  parent we materialized from* (a compare-and-set on the head pointer; e.g.
  `UPDATE … WHERE head = :parent` or an append-only manifest table with a
  unique `(workspace_id, parent)` constraint).
  *(Refinement, 2026-07-02, from the phase-1b plan: heads are per-**prefix** —
  shared, private-per-user — not one per household. A single household-wide
  head cannot work under RLS: a joint run's flush would have to copy forward
  private manifest entries it cannot read, so private files would vanish from
  the head. Per-prefix chains preserve every guarantee — each CAS is atomic and
  lost-update-safe, and a joint run only ever holds the shared head.)* Blobs are uploaded to R2
  **first** (immutable, side-effect-free; orphans from a losing race are
  harmless and GC-able), so the only mutating step is the single CAS on the head
  — making the commit atomic and leaving no half-applied state. If the CAS
  fails, the head moved: re-materialize the new head, re-apply the diff
  (memory/rules are append-ish markdown that 3-way-merges cleanly), retry the
  CAS. With two users, contention is rare.
- **Visibility routing on write-back:** each changed file flushes back to the
  prefix it was materialized from (shared → shared prefix; private → owner's
  private prefix). A **joint session only ever materialized shared files, so it
  can only write shared** — private data can't leak outward even on write. New
  files default to **private** in an individual session (promotable to shared
  explicitly) and to **shared** in a joint session (the only scope available).

### Agent-context injection (unchanged intent)

- Memory/rules/reports carry owner/visibility; the loader injects them into
  `{{AGENT_MEMORY}}` per the read flow above.
- **Individual session:** own-private + shared. **Joint session:** shared-only.
- A merchant rule targeting a private account is private to that user and never
  enters the spouse's (or a joint) agent context.

## Plaid-token encryption (security fold-in)

`plaid_items.access_token` is plaintext today. Since we are already migrating
that table, encrypt it at rest now (app-level envelope encryption via a key from
env, `PENNY_PLAID_TOKEN_KEY`) rather than leaving a plaintext-secrets table for
the later audit. Decryption happens only when calling Plaid.

## Migration of existing single-user data

Existing real data lives in Neon Postgres with no tenant columns. Standard
**expand → backfill → contract**, appended to the Alembic `000→005` chain:

1. Create one `households` row (yours) and two `users` rows (you + wife); you own
   the existing links. Revive/populate `plaid_accounts` from current Plaid data.
2. Add new columns **nullable**; backfill every row to your household, you as
   owner, `visibility='private'` by default. Then flip specific accounts to
   `shared`.
3. Make columns `NOT NULL`, add FKs + indexes, enable RLS policies. Encrypt
   existing `access_token`s in the same pass.

SQLite local dev gets the columns but no RLS.

## Testing strategy

Multi-tenancy lives or dies here.

- **Two-household leakage suite:** seed households A and B; assert every façade
  method *and* a battery of `run_sql` queries from A's context return **zero** B
  rows.
- **Within-household privacy suite:** wife's private account is invisible to you;
  a shared account is visible to both.
- **Joint-session suite:** a joint run sees shared-only; neither spouse's private
  transactions, memories, or reports appear.
- **Workspace suite:** (a) joint session never resolves a private prefix —
  private bytes never reach the temp dir; (b) concurrent flushes — two runs off
  the same parent: one CAS wins, the loser re-materializes and retries, and no
  half-applied state or lost update results; (c) an aborted run commits nothing.
- RLS tests run against **Postgres (Neon test branch)**, not SQLite, since SQLite
  won't enforce policies.

## Out of scope (sub-project 1)

- Real authentication (phase 2; phase 1 uses a dev-stub principal).
- Signup / onboarding UI (phases 4–5).
- Multi-household membership (one household per user for now).
- Per-account *override* of merchant normalization (global for now).

---

# Roadmap: phases 2–6 (to be specced individually)

- **Phase 2 — Auth / social login.** Clerk or Auth0 with Google sign-in,
  all-list limited to you + wife. Replace the dev-stub principal with verified
  JWT → `RequestContext`. Add auth middleware in FastAPI; frontend gets a login
  screen and attaches tokens. Map `external_auth_id` → `users`.
- **Phase 3 — Provision + test.** Create the two real users in one household,
  link real banks, set per-account visibility, validate individual + joint
  sessions against real data.
- **Phase 4 — Signup / account-creation UI.** Self-serve account creation
  (still gated to invited emails), household bootstrap, taxonomy seed on create.
- **Phase 5 — Onboarding.** Guided Plaid linking, taxonomy customization,
  merchant-rule setup, first-sync experience.
- **Phase 6 — Security audit.** Adversarial cross-tenant leakage review, RLS
  policy audit, secret-handling review, prompt-injection testing of `run_sql`
  under RLS, dependency + transport review. **Explicit focus items:** the **R2
  access path** (RLS protects the pointer, not the bytes — verify opaque tokens,
  no-`LIST` scoped credentials, app-derives-keys-only-from-RLS-lookups, no direct
  agent R2 capability) and the **workspace concurrency model** (CAS atomicity, no
  lost updates, temp-dir teardown/hygiene).
