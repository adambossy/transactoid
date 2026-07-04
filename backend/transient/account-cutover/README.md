# Phase-3 Production Cutover (`penny-cutover`)

**TRANSIENT / NON-CANONICAL** one-off tool (see the repo `AGENTS.md`). It moves
the existing single-user production data into the multi-tenant world. It is
exempt from the lint/test gate, is **not** imported by any app code, may import
the canonical phase-1a models/façade + token cipher **read-only**, and is
**deletable** once the cutover is verified complete. Its correctness bar is the
rehearsal `verify` passing + the zero-unassigned post-condition + the Phase-6
suites green against the migrated data — not the unit gate.

Plan: `docs/superpowers/plans/2026-07-03-phase-3-cutover.md`
Spec: `docs/superpowers/specs/2026-07-03-phase-3-cutover-design.md`

## What it does

A `penny-cutover` Typer CLI of ordered, **idempotent, resumable** stages, each
`--dry-run`-able, that applies the epic migration chain **in two halves** around
an interactive per-account owner/visibility assignment:

```
backup            step 0: frozen Neon restore branch (untouched until verify)
reconcile-expand  stamp prod's alembic baseline + apply the EXPAND half (010–013)
bootstrap         create the household + two PENDING users (external_auth_id NULL)
assign-accounts   interactively assign each linked account's owner + visibility
reparent          apply the mapping, denormalize onto children, assert 0 unassigned
finalize-schema   apply the CONTRACT half (014 → head) now that every row is assigned
verify            isolation/privacy checks on the migrated data (gates backup release)
```

The two halves exist because the NOT-NULL / RLS contract (014+) can only land
**after** every legacy row has an owner — so the interactive assignment sits
between `reconcile-expand` (stops at 013) and `finalize-schema` (`upgrade head`).
Prod identity + ownership are created **here**, by these stages — never by a
migration (013's dev backfill is a prod no-op; 016 backfills categories to the
household id the finalize stage passes it).

Every stage records progress in `.cutover-state.json` (which stages finished,
the frozen branch name, the bootstrapped household + user ids), so a re-run
resumes rather than repeats.

## Invocation

Run from `backend/` so the canonical `penny` package imports resolve:

```bash
cd backend
DATABASE_URL="<REHEARSAL-branch-url>" \
  uv run python transient/account-cutover/cli.py <stage> [--dry-run] [opts...]
```

`--db-url` overrides `$DATABASE_URL`. **Point it at the rehearsal branch, never
prod, until the rehearsal `verify` passes.**

## Safety order (never skip)

1. **Frozen backup** — `backup` creates a Neon branch off prod and records it.
   It is the restore point and is **not touched again until `verify` passes**.
2. **Rehearse on a clone** — create a *separate* throwaway Neon branch off prod
   and run every stage end-to-end against it; confirm `verify` passes and the
   Phase-3 browser E2E is green. This is a different branch from the frozen
   backup.
3. **Pre-apply snapshot** — immediately before the prod apply, take a fresh
   snapshot/branch of prod (belt-and-suspenders beside the step-0 frozen
   branch).
4. **Prod apply** — run the stages against prod.
5. **Restore path** — if anything is wrong, restore prod from the step-0 frozen
   branch (the `backup` stage prints the exact `neonctl branches restore`
   command).

The full operator runbook (rehearse → execute) is in
[the runbook section](#operator-runbook-rehearse--execute).

## Restore

`backup` prints, on creation and on every re-run, the command that overwrites
prod with the frozen snapshot:

```bash
neonctl branches restore <prod-branch> <frozen-branch> [--project-id <id>]
```

## Pending-user signup handoff (needs Phase 4)

`bootstrap` seeds the household + two **pending** `users` (your email, your
spouse's; `external_auth_id NULL`) — no Clerk objects, no passwords. Claiming a
pending row needs each spouse to *create* a Clerk identity and sign in, which is
the **Phase-4 `<SignUp>` surface** (Phase 2 only wires `<SignIn>`). So Phase 4
must ship before this step. The handoff, once the data-migration stages are
done and Phase 4 is live:

1. You sign up via the Phase-4 flow with your invited email. Phase-2 first-login
   linking matches your **verified** email to your pending `users` row and
   claims it (sets `external_auth_id`). You land in the migrated household with
   your assigned accounts already owned correctly.
2. Your spouse signs up with their invited email; same linking. They land in the
   **same** household, seeing their accounts + shared accounts, and **never**
   your private accounts (the `verify` RLS battery proves this held).

No merge, no special-casing — it reuses the invite/link mechanism exactly.

## `verify` gates the backup release

`verify` runs three batteries against the migrated data — zero unassigned tenant
columns, all Plaid tokens ciphertext, and the RLS isolation proof (a private
account owned by one spouse returns zero rows in the other's tenant context).
**Run it as the non-superuser app role** (`--app-db-url`): a superuser/BYPASSRLS
role sees everything and would give a false pass — verify refuses to claim an RLS
pass from a bypassing role. Only when `verify` exits 0 is the frozen step-0
backup branch releasable.
