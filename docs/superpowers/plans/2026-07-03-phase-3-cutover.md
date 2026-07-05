# Phase 3 — Production Cutover & Legacy-Data Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **This is transient, non-canonical code** (per AGENTS.md): it lives in `backend/transient/account-cutover/`, is exempt from the lint/test gate, is not imported by app code, and is deletable once the cutover completes. Its correctness bar is the rehearsal `verify` passing + the post-condition assertions + the Phase-6 suites green against the migrated data — not the unit gate.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 3 cutover design](../specs/2026-07-03-phase-3-cutover-design.md).
> **Depends on:** Phases 1a, 1b, 2 — **and Phase 4** (the handoff needs `<SignUp>`). Build 4 before the handoff step.

**Goal:** One-time, programmatic, account-aware cutover of the existing
single-user production data into the multi-tenant world — backup, reconcile,
bootstrap pending users, interactively assign per-account owner/visibility,
re-parent, verify — safely and rehearsably.

**Architecture:** A `penny-cutover` Typer CLI with ordered, idempotent, resumable
stages, each `--dry-run`-able. It applies the epic migration chain **in two
halves** (expand 010–013 → interactive assign/reparent → contract 014–019)
because the NOT-NULL/RLS contract can only land after every legacy row is
assigned. Prod identity + ownership are created **here**, not by any migration.

**Tech Stack:** Python 3.12, Typer, Alembic, `neonctl` (branch backup/rehearsal),
the phase-1a façade/models (read-only import), the phase-1a token cipher.

## Global Constraints

- **Non-canonical.** All code under `backend/transient/account-cutover/`. May
  import canonical app models/façade read-only; no app code imports it. Frozen
  after use; not in the verification gate.
- **Safety order (never skip):** step-0 **frozen Neon branch backup** (untouched
  until `verify` passes) → full **rehearsal on a separate Neon branch clone** →
  **pre-apply snapshot** → prod apply.
- **Idempotent + resumable:** every stage can re-run; `assign-accounts` appends
  to a mapping record file so a re-run resumes rather than re-prompts.
- **Post-condition:** after `reparent`, assert **zero rows with a null/unassigned
  tenant column** across all scoped tables; fail loudly otherwise.
- **Migration numbers:** per the epic ledger — expand = `010`–`013`, contract =
  `014`–`018` (finance) + `019` (web conversations). The cutover does not create
  new numbered migrations; it *applies* the epic's chain in two `alembic upgrade`
  calls around the data assignment.

## File structure

```
backend/transient/account-cutover/
├── cli.py                    # `penny-cutover` Typer app: the ordered stages
├── stages/
│   ├── backup.py             # frozen Neon branch (restore point)
│   ├── reconcile.py          # legacy multi-head merge + stamp; upgrade to 013 (expand)
│   ├── bootstrap.py          # household + pending users
│   ├── assign.py             # interactive owner/visibility prompts -> mapping file
│   ├── reparent.py           # apply mapping; denormalize; post-condition assert
│   ├── finalize.py           # upgrade 014->019 (contract) after assignment
│   └── verify.py             # isolation/privacy checks on migrated data
├── mapping.example.yaml
└── README.md                 # runbook + safety order
```

---

### Task 1: CLI skeleton + `backup` (frozen Neon branch)

**Files:** create `cli.py`, `stages/backup.py`, `README.md`.

- [ ] `penny-cutover` Typer app with subcommands `backup / reconcile-expand /
  bootstrap / assign-accounts / reparent / finalize-schema / verify`, each
  accepting `--db-url` and `--dry-run`, resumable (each records progress in a
  `.cutover-state.json`).
- [ ] `backup`: create a frozen Neon branch of the target (via `neonctl branches
  create`), record its name in the state file, print the restore command. Refuse
  to proceed if a prior frozen branch for this run already exists (idempotent).
- [ ] README documents the safety order (backup → rehearse on clone → pre-apply
  snapshot → prod) and the restore path.
- [ ] Commit `chore(cutover): CLI skeleton + frozen-branch backup stage`.

---

### Task 2: `reconcile-expand` (legacy multi-head + expand half)

**Files:** `stages/reconcile.py`.

- [ ] Resolve the **legacy** multi-head history to a single head
  (`alembic merge`), `alembic stamp` the revision matching the target's current
  `create_all` schema so alembic treats the baseline as applied.
- [ ] `alembic upgrade 013` — apply the **expand** half only (identity tables
  `010`, `plaid_accounts` `011`, nullable tenant columns `012`, dev-only backfill
  `013` which is a **no-op on prod**). Legacy rows still have null tenant columns
  — expected.
- [ ] `--dry-run` prints the plan (current head, merge target, revisions to run)
  without executing. Confirm on the rehearsal branch first.
- [ ] Commit `chore(cutover): reconcile legacy heads + apply expand half (010-013)`.

---

### Task 3: `bootstrap` (household + pending users)

**Files:** `stages/bootstrap.py`.

- [ ] Create one `households` row and two **pending** `users` rows (your email,
  your wife's; `external_auth_id` NULL) — no Clerk objects. Idempotent (skip if
  present). Record the household + user ids in the state file.
- [ ] Commit `chore(cutover): bootstrap household + pending users`.

---

### Task 4: `assign-accounts` (interactive) + mapping record

**Files:** `stages/assign.py`, `mapping.example.yaml`.

- [ ] Query the linked accounts (from `plaid_accounts` / distinct
  `plaid_transactions.account_id` + institution + a few sample transactions for
  recognition). For each **not yet in the mapping file**, prompt **owner**
  (you/wife) and **visibility** (private/shared); append the choice to
  `accounts.mapping.yaml` immediately (resume-safe).
- [ ] Validate at the end: every account has an owner + visibility; the two
  owners map to the two pending user ids.
- [ ] Commit `chore(cutover): interactive account owner/visibility assignment`.

---

### Task 5: `reparent` (apply mapping + post-condition)

**Files:** `stages/reparent.py`.

- [ ] For each account in the mapping, one transaction: set `owner_user_id` +
  `household_id` + `visibility` on the `plaid_item`/`plaid_account`, denormalize
  onto every child transaction/item; assign household-only tables (categories,
  tags, conversations) to the household.
- [ ] Encrypt any legacy plaintext `plaid_items.access_token` (key-version cipher).
- [ ] **Post-condition assertion:** a query proving **zero rows remain with a
  null/unassigned tenant column** across all scoped finance + web tables; abort
  loudly otherwise (so nothing slips before the contract lands).
- [ ] `--dry-run` reports counts per account without writing.
- [ ] Commit `chore(cutover): re-parent legacy data + zero-unassigned assertion`.

---

### Task 6: `finalize-schema` (contract half)

**Files:** `stages/finalize.py`.

- [ ] Now that every row is assigned, `alembic upgrade head` — the **contract**
  half: `014` (NOT NULL + FK + CHECK visibility + CHECK owner≠nil + indexes),
  `015` (RLS USING+WITH CHECK), `016` (categories household), `017` (encrypt),
  `018` (workspace), and the web chain `019` (conversation tenancy + RLS). These
  can only land after re-parent.
- [ ] Commit `chore(cutover): apply contract half (014-019) after assignment`.

---

### Task 7: `verify` + handoff runbook

**Files:** `stages/verify.py`, `README.md` (handoff section).

- [ ] `verify`: run the isolation/privacy checks against the migrated data — a
  `run_sql`-style battery from each user's context returns only their + shared
  rows; no unassigned rows; tokens are ciphertext. Only when `verify` passes is
  the frozen backup branch releasable.
- [ ] **Handoff (runbook, needs Phase 4):** you and your wife sign up via the
  Phase-4 `<SignUp>` flow with the invited emails → Phase-2 first-login linking
  claims your pending rows → you each land in the migrated household with your
  assigned accounts. Document the exact steps.
- [ ] Commit `chore(cutover): verify stage + pending-user handoff runbook`.

---

### Task 8: Rehearse → execute (runbook, operator)

Not code — the operator sequence (documented in README, executed by you):

- [ ] Rehearse the whole sequence (Tasks 1–7 stages) on a **separate Neon branch
  clone** of prod; confirm `verify` passes and the browser E2E from the phase-3
  spec is green (sign in as each spouse, see the right accounts, private hidden).
- [ ] Take the **pre-apply snapshot**, then run the stages against **prod**.
- [ ] Confirm; if anything is wrong, **restore from the step-0 frozen branch**.
- [ ] After success + Phase-6 suites green on the migrated data, the cutover is
  complete; the transient directory may be archived/removed per AGENTS.md
  (keep the record; don't maintain it).

---

## Self-Review

**Spec coverage:** backup (frozen branch) → Task 1; alembic reconciliation + two
halves → Tasks 2/6; bootstrap pending users → Task 3; interactive assignment +
mapping file → Task 4; reparent + post-condition → Task 5; verify → Task 7;
handoff (depends on Phase 4) → Task 7; safety/rehearse/restore → Tasks 1/8;
create_all-fixed-for-good (alembic-only on prod, single head) → Tasks 2/6 +
Phase-6 CI drift guard.

**Placeholder scan:** stages are described operationally (this is transient
one-off code, held to the rehearsal/verify bar, not the unit gate) — deliberate
per AGENTS.md non-canonical rules. No TBD.

**Type/interface consistency:** stage names match the spec's flow and the CLI
subcommands; migration numbers (010–019) match the epic ledger; reuses phase-1a
models/cipher read-only.

## Execution Handoff

Operator-driven (executing-plans), not subagent-per-task — the interactive
assignment and the prod apply need a human in the loop. Requires `neonctl` +
access to the prod and test Neon branches. **Do not run against prod until the
rehearsal `verify` passes and Phase 4's signup surface exists** for the handoff.
