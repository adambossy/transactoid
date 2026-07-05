# Phase 3 — Production Cutover & Legacy-Data Migration — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-03
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** Phases 1a, 1b, 2 — **and Phase 4** (the cutover's completion
requires the Phase-4 signup surface; see §4). Build order: Phase 4 ships
**before** the cutover's handoff/verify. The data-migration stages (backup →
reconcile-expand → bootstrap → assign → reparent → finalize) can run before
Phase 4; only the handoff + `verify` need it.
**Repurposed from** the old "Provision + test" phase (provisioning → Phase 4,
validation → Phase 6).

## Goal

A one-time, **fully programmatic** cutover that moves the existing single-user
production data into the multi-tenant world: reconcile prod's schema, create the
household + pending users, interactively assign each linked account's owner and
visibility, re-parent all legacy transactions accordingly, and hand off to
Phase-4 signup — safely, rehearsable, and with a frozen restore point.

## Decisions (locked)

- **Transient, segregated code.** The cutover lives in
  `backend/transient/account-cutover/` — a **non-canonical** directory (per the
  AGENTS.md changes in progress): not imported by application code, exempt from
  the canonical lint/test gate, and **deletable once the cutover is complete**.
- **Interactive account assignment**, with every choice written to a mapping
  record file as it's made (resume-safe, auditable, re-runnable without
  re-prompting).
- **Backup = a frozen Neon branch** taken as step 0 and left untouched until the
  entire cutover is verified complete (the restore point), *separate* from the
  rehearsal branch clone.
- **Alembic becomes prod's sole schema authority** after reconciliation (see
  §2) — `create_all` stops running against prod.
- **Pending-user handoff:** the cutover seeds pending `users`; Phase-4 first-login
  linking claims them. No merge, no special-casing.

## Where the code lives (proposal)

```
backend/transient/                      # non-canonical; one-off actions; not app code
└── account-cutover/
    ├── cli.py                          # `penny-cutover` (Typer): the ordered stages
    ├── stages/                         # reconcile_schema / bootstrap / assign / reparent / verify
    ├── mapping.example.yaml            # shape of the account→owner/visibility record
    └── README.md                       # runbook + safety order
```

AGENTS.md gains a line marking `backend/transient/**` non-canonical (excluded
from ruff/pytest gates and from "follow existing patterns" expectations; treat as
scratch). The cutover may import canonical app models/façade read-only, but no
app code imports `transient/`.

## Section 1 — Cutover flow & components

A `penny-cutover` CLI with ordered, **idempotent, resumable** stages, each
supporting `--dry-run`:

0. **`backup`** — create a **frozen Neon branch** of prod (the restore point);
   record its name; do not touch it again until `verify` passes.
1. **`reconcile-expand`** — bring prod's alembic state in line and apply the
   **expand half** of the chain: `006`–`009` (identity tables, `plaid_accounts`,
   nullable tenant columns; migration `009` is a **no-op on prod**). Legacy rows
   still have null tenant columns at this point — that's expected. (§2)
2. **`bootstrap`** — create the household + **pending** `users` rows (you + wife;
   `external_auth_id` NULL).
3. **`assign-accounts`** — list each linked account and interactively prompt
   owner + visibility (§3), writing each answer to the mapping record file.
4. **`reparent`** — apply the mapping; set tenancy on every item/account and
   denormalize onto all child rows; assert zero unassigned rows (§3).
5. **`finalize-schema`** — now that every row is assigned, apply the **contract
   half**: `010`–`013` (NOT NULL, FKs, CHECKs, RLS, per-household categories,
   token encryption), `014` (1b workspace), `015` (conversation tenancy + web
   RLS). The NOT-NULL/RLS contract can only land *after* re-parent.
6. **`verify`** — run the isolation/privacy checks against the migrated data
   (feeds Phase 6); only after this passes is the cutover "complete."

**Run order:** step 0 backup → full **rehearsal on a separate Neon branch clone**
(run every stage, verify) → **pre-apply snapshot** → prod apply.

## Section 2 — Prod alembic reconciliation (and fixing `create_all` for good)

Prod is `create_all`-managed with multi-head alembic history, so `upgrade head`
alone is unsafe. `reconcile-schema`:

1. On a throwaway Neon branch off prod: resolve the **legacy** multi-head history
   to a single head (`alembic merge`), `alembic stamp` the revision matching
   prod's current `create_all` schema (alembic now believes the baseline is
   applied). The new epic migrations are a **single linear chain** per the
   ledger (1a `006`–`013` → 1b `014` → 2 `015`), so the only merge needed is for
   the *legacy* split — the epic manufactures no new head.
2. Apply the chain **in two halves around the data assignment** (stages 1 and 5):
   `upgrade` to `009` first (expand), then bootstrap/assign/reparent, then
   `upgrade head` (`010`→`015`, contract). This is why the NOT-NULL/RLS contract
   can't be a single `upgrade head` on prod.
3. Rehearse the full sequence on the branch; confirm schema + a smoke query;
   then repeat on prod after the pre-apply snapshot.

**Making it stick (so `create_all` drift can't recur):**
- On prod, `bootstrap()` runs **`alembic upgrade head` only** — `create_all`
  stays for SQLite dev, never prod.
- Every future schema change ships as a migration; migration branches get
  `alembic merge`d to keep a single head.
- A **CI drift guard** (`alembic check` / empty autogenerate diff) catches
  regressions — wired in **Phase 6's** CI job.

Reconciliation is the one-time fix; these three keep it fixed.

## Section 3 — Interactive assignment & re-parenting

- `assign-accounts` shows each linked account (institution, name, a few sample
  transactions for recognition) and prompts **owner** (you/wife) and
  **visibility** (private/shared), appending each choice to the mapping record
  file (so a re-run resumes rather than re-prompts).
- `reparent` applies the mapping, one transaction per account: set
  `owner_user_id` + `household_id` + `visibility` on the `plaid_item` /
  `plaid_account`, denormalize onto every child transaction/item, and assign
  household-only tables (categories, tags, conversations) to the household.
- **Post-condition:** a query asserting **zero rows remain with a null/unassigned
  tenant column** across all scoped tables; `reparent` fails loudly otherwise, so
  nothing slips through before the `NOT NULL`/RLS contract is enforced.

## Section 4 — Pending-user signup handoff

- `bootstrap` seeds the household + two **pending** `users` rows (your email,
  your wife's; `external_auth_id` NULL) — no Clerk objects, no passwords.
- **This handoff requires the Phase-4 signup surface** (series-review fix):
  claiming a pending row needs each spouse to *create* a Clerk identity and
  sign in, and Phase 2 only wires `<SignIn>` — brand-new-account creation
  (`<SignUp>`) arrives in Phase 4. **So Phase 4 must ship before this step.**
  The build order is therefore …→ Phase 2 → Phase 4 → **Phase 3 handoff/verify**
  (the earlier data-migration stages may run before Phase 4).
- You each sign up via the **Phase-4 flow** (`<SignUp>` with your invited
  emails); Phase-2 first-login linking matches your verified email to the
  pending row and claims it. You land in the migrated household with your
  assigned accounts already owned correctly; your wife lands in the same
  household seeing her accounts + shared ones, **not** your private accounts.
  Reuses the invite/link mechanism exactly.

## Section 5 — Safety & validation

- **Safety:** step-0 frozen-branch backup (untouched until `verify` passes); full
  rehearsal on a separate Neon branch clone; pre-apply snapshot; every stage
  idempotent/resumable with `--dry-run`; `reparent` post-condition assertions.
- **Restore:** if prod apply goes wrong, restore from the frozen step-0 branch.

## UI/UX Requirements

- As the operator, I run the cutover entirely from the CLI; it introduces **no
  new screens**.
- As you (post-cutover), I sign in and see exactly my assigned accounts plus
  shared ones — no visible trace that a migration happened.
- As your wife (post-cutover), I sign in and see my accounts plus shared ones,
  and never your private accounts.

Any incidental UI (none expected) would use the shared UI template primitives
(Header, Footer, Logo, color tokens, type scale, font stack), responsive, with
loading/empty/error states, and a consistent app shell.

## Browser E2E validation (Playwright)

The cutover's proof is end-to-end through the real UI (reusing the phase-1a
harness + `signInAsTestUser`, run against the rehearsal branch):

- After cutover + signup, signing in as **you** shows your assigned accounts +
  shared accounts; a private account you own is visible.
- Signing in as **your wife** shows her accounts + shared accounts, and a
  Playwright assertion confirms **your private accounts never render** in her
  session (the assignment held end-to-end).
- The Phase-6 isolation suites also run against the migrated dataset.

## Testing strategy

- The cutover stages are exercised on the **rehearsal Neon branch** end to end
  before prod.
- Because the code is transient/non-canonical, it isn't held to the app's unit
  gate; instead its correctness bar is: the rehearsal run's `verify` stage passes,
  the post-condition assertions hold (zero unassigned rows), and the browser E2E
  + Phase-6 suites are green against the migrated data.

## Out of scope

- Provisioning / signup UI (Phase 4) and the admin household/user CLI (a minor
  Phase-4 utility).
- The security audit itself (Phase 6) — the cutover only *feeds* it.
- Re-usable, canonical migration tooling — this is a one-off; if a second cutover
  is ever needed, generalize then.

## Modularization note

The cutover is deliberately **non-reusable** (transient one-off), so it is *not*
a modularization target. But it exercises the reusable tenancy/account model
(households, users, `plaid_accounts`, `RequestContext`) — if that model is later
extracted into a portable package (see the epic's modularization pass), the
cutover would consume it read-only without change.
