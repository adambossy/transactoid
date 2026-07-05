# Phase 1b — Execution Decisions

Ambiguities encountered while executing
`docs/superpowers/plans/2026-07-02-phase-1b-workspace-hybrid.md` and the
decisions made (with rationale). This file is owned solely by the phase-1b
executor.

## D0 — Worktree base was `main`, not `feat/account-creation`

**Ambiguity/blocker:** The task states the worktree is branched off
`feat/account-creation` (which contains Phase 1a). In reality the worktree
branch pointed at `main` (an older fork point, `f083dab`), so it lacked
`penny/tenancy/`, the finance migration chain, and the plan/spec docs.

**Decision:** Merged `feat/account-creation` into the worktree branch
(non-destructive — the branch had no unique commits). A `git reset --hard`
was denied by the safety classifier, and a merge is anyway safer: it preserves
main's script-segregation commits while bringing in the full Phase 1a base +
docs. Phase 1b work is layered on top; when merged back into
`feat/account-creation` the diff is just the Phase 1b commits (plus the already
merged history).

## D1 — Workspace tables added to `rls.py` OWNER_VIS_TABLES (Task 2/8)

**Ambiguity:** Task 2 lists models.py + migration + alembic env.py as the RLS
surface, but the Task 8 RLS battery runs against the `pg_db` fixture, which
RLS-enables tables via `penny.adapters.db.rls.enable_rls` (the module lists),
*not* by running migration 018.

**Decision:** Appended `workspace_prefixes` / `workspace_manifests` /
`workspace_heads` to `OWNER_VIS_TABLES` in `rls.py` so the pg_db fixture (and
any future `enable_rls` caller) protects them. Migration 015 keeps its own
frozen local list, so this does not retroactively change 015. Migration 018
enables RLS on prod via the same `household_policy_ddl` shape — single source.

## D2 — `workspace_dir` threaded as an optional param (Task 6)

**Ambiguity:** Task 6 says `_assemble_agent_memory`/`build_agent`/
`_render_system_prompt` should read the checkout, but existing tests
(`test_prompt_rendering.py`) call `_render_system_prompt(ctx)` and expect the
legacy `~/.transactoid` memory.

**Decision:** Added `workspace_dir: Path | None = None` to all three; when
provided (the per-run checkout) it wins, else the legacy workspace dir. This
keeps existing tests green and threads the checkout through the new front-door
path. `build_agent` roots a fresh `InProcessSandbox` at `workspace_dir` so the
agent's filesystem edits (memory/reports) land where `flush` picks them up;
without it the process-wide singleton sandbox is used (scripts/tests).

## D3 — Streaming chat handler inlines materialize→flush (Task 6)

**Ambiguity:** The plan says wrap the chat handler as
`await run_with_workspace(ctx, lambda root: ...)`. But `/api/chat` returns a
streaming SSE generator that must *yield* frames as they arrive; it cannot be
expressed as `await run_fn(root)` returning a single result.

**Decision:** `run_with_workspace` is used verbatim for the non-streaming CLI
front door (`cli._drive_agent`) and the admin import. The streaming chat
handler composes the *same* primitives (`ensure_prefixes` → `materialize` →
stream → `flush`, temp dir torn down in `finally`) inline. No core logic is
duplicated — materialize/flush are the reusable seam; `run_with_workspace` is
only sugar for the awaitable case. Aborted stream never reaches `flush`.

## D4 — `test_cli.py` stubs `run_with_workspace` (Task 6)

**Ambiguity:** The CLI smoke test stubs `bootstrap` (no schema) and has no
isolated DB, so wiring the real store lifecycle into `_drive_agent` would make
it hit `get_db()`/R2.

**Decision:** Stubbed `run_with_workspace` in that test to hand `run_fn` a
throwaway temp dir. The test's purpose is "the CLI reaches `build_agent` and
maps the outcome to an exit code"; the store lifecycle is separately covered by
`tests/workspace_store/test_agent_wiring.py`. Not editing a plan/spec file.

## D5 — Task 8 RLS battery verified against a real local Postgres

**Ambiguity:** The Postgres suites skip without `POSTGRES_TEST_URL`, and the
stale Neon creds meant no test branch was reachable.

**Decision:** Stood up a throwaway Dockerized Postgres 16 with a **non-superuser**
`penny_rls` role (superusers bypass RLS) and ran the marked suites for real:
all 5 new workspace RLS tests pass, alongside the 4 existing phase-1a RLS tests
(9 passed; full `-m postgres` set 14 passed). Migration 018's RLS DDL reuses
the exact `household_policy_ddl` path the passing suite exercises via
`enable_rls`, so both halves of 018 (table DDL mirroring create_all, and RLS
policy) are independently proven on Postgres. The container was torn down.

## D6 — Full `alembic upgrade head` fails at 001 on fresh Postgres (pre-existing)

**Observation, not a change:** Running the whole chain on a fresh Postgres
fails at migration 001 because Alembic's default `alembic_version.version_num`
is `VARCHAR(32)` and this repo's revision ids (e.g.
`001_add_transaction_items_and_split_columns`, 43 chars) overflow it. This is
pre-existing (see MEMORY: "alembic_version varchar(32) quirk"; prod is
create_all-managed, not migration-run). Migration 018 follows the same naming
convention and reaches head cleanly on SQLite (verified). I did **not** touch
the pre-existing quirk — out of scope for this phase and prod does not run the
chain.

## D7 — Task 9 (frontend E2E spec) NOT created — orchestrator hard rule

**Conflict:** Plan Task 9 creates `frontend/e2e/workspace-memory.spec.ts`, but
the orchestrator's hard rules state: "Do NOT modify anything under `frontend/`."
Creating a new file under `frontend/` violates that constraint.

**Decision:** Honored the orchestrator hard rule (it overrides the plan) and did
**not** create the frontend spec. The E2E is also un-runnable in this backend
verification gate: it needs the live app + a real model key
(`PENNY_E2E_MODEL`) and is `test.skip`-gated otherwise. The backend store
round-trip it would exercise is already proven by the unit suite
(`test_sync.py` materialize→flush→re-materialize across runs) and the live
Postgres RLS battery. Flagged to the orchestrator as the one intentionally
skipped task.
