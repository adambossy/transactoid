# pennydb — target-explicit database tooling

**Date:** 2026-07-12
**Status:** approved

## Problem

DB work happens against three very different targets — the Neon `production`
branch, a one-off Neon test branch (via `new_test_branch.sh` / `.env.test`),
and local SQLite — and nothing about an ad-hoc `psql "$CS"` or
`neonctl connection-string` invocation says which one it's hitting. Two
concrete failures this week:

- The prod `PENNY_AGENT_READONLY_DATABASE_URL` secret had been pointing at the
  *test* branch's endpoint (`ep-cold-field`), and broke when that branch was
  recreated.
- `.env.test` exists only in the main checkout, so Claude sessions in
  worktrees improvise with `neonctl connection-string --branch-name production`
  — which silently hands out **prod**.

Claude sessions should be dev-by-default; prod DB work is the rare, explicit
exception.

## Design

One wrapper script, `backend/scripts/pennydb` (bash, checked in — dev tooling,
not deploy, not app code). The **target is the mandatory first argument**;
there is no default target.

```
pennydb test psql [psql args…]     # psql against the session test branch
pennydb test url                   # print the test DATABASE_URL (stdout only)
pennydb test exec -- <cmd…>        # run any command with the test env loaded
                                   #   (uvicorn, pytest, alembic upgrade…)
pennydb test refresh               # delegate to new_test_branch.sh
pennydb prod psql [psql args…]     # READ-ONLY psql against production
pennydb prod psql --write [args…]  # explicit write session
pennydb prod url [--role <name>]   # print prod URL, resolved live (default
                                   #   role neondb_owner)
pennydb selftest                   # offline checks of parsing/banner logic
```

Every invocation prints a one-line banner **to stderr** before acting:

- `>> TEST  branch test-20260712-… @ ep-… ` (green)
- `!! PROD  production @ ep-divine-cake… (READ-ONLY)` (red)
- `!! PROD  production @ ep-divine-cake… (WRITE)` (red, bold)

Prod read-only is real, not cosmetic: `psql` runs with
`PGOPTIONS="-c default_transaction_read_only=on"` unless `--write` is given.

### Credential resolution

- **Test:** `new_test_branch.sh` writes the env file to
  `~/.transactoid/env.test` (the per-machine workspace, shared by all
  worktrees) and leaves `backend/.env.test` as a symlink to it in the checkout
  that ran it (back-compat with the documented `source .env.test` loop; other
  checkouts may keep a stale real file — `pennydb` never reads it).
  `pennydb test *` reads `~/.transactoid/env.test`; if missing it errors with
  "run `pennydb test refresh`" (exit 2); if older than 7 days it warns
  (stderr) that the branch is stale.
- **Prod:** resolved at call time via
  `neonctl connection-string --branch-name production --role-name <role>`.
  Never cached, never written to disk.
- **Shared constants:** `backend/scripts/neon_env.sh` holds
  `ORG_ID` / `PROJECT_ID` / `PROD_BRANCH` / `DB_NAME` / `ROLE_NAME` /
  `TEST_PREFIX` / `PROTECTED_BRANCHES`; both `pennydb` and
  `new_test_branch.sh` source it (single source of truth).

### Claude-session enforcement

Project `.claude/settings.json` (checked in):

- **deny:** `Bash(psql:*)`, `Bash(neonctl connection-string:*)` — raw access
  is refused in sessions; the wrapper is the only path.
- **allow:** `Bash(backend/scripts/pennydb test:*)` and
  `Bash(scripts/pennydb test:*)` — dev work flows without prompts.
- `pennydb prod …` matches neither list → a permission prompt on every use,
  and an approved prompt still can't write without `--write`.

Humans in a plain terminal are unaffected (settings only bind Claude
sessions).

### Docs

- AGENTS.md dev-loop section: replace the `source .env.test` incantation with
  `pennydb test exec -- uvicorn …` (keep the old form as a note).
- AGENTS.md Databases section: short "Database access" bullet — use
  `pennydb`, dev-by-default, what prod mode means, `--role-name` now required
  for raw `neonctl connection-string` (multiple roles exist on production).

### Error handling

- Missing env file → actionable message + exit 2.
- `neonctl` missing/unauthenticated → surface its stderr + hint
  (`neonctl auth`), exit 1.
- Unknown target/subcommand, bare `pennydb` → usage on stderr, exit 2.
- Banner on stderr keeps `pennydb test url | pbcopy` clean.

### Testing

`pennydb selftest` runs the offline paths against fixtures (temp
`PENNYDB_ENV_FILE`): arg parsing, env-file parsing, URL extraction, stale
warning, usage errors, banner target/host rendering. No network. The prod
read-only guard is verified once manually (`CREATE TABLE` must fail with
`cannot execute CREATE TABLE in a read-only transaction`).

## Out of scope

- `pennydb prod migrate` — prod migrations are owned exclusively by the deploy
  release command (`penny migrate`); emergencies go through
  `pennydb prod psql --write`.
- SQLite dev DB — untouched; it's the app's default and carries no
  cross-target risk.
- The user-global WorktreeCreate hook that copies env files into new worktrees
  — superseded for DB purposes by the shared `~/.transactoid/env.test`, but
  harmless and out of this repo's scope.

## Alternatives considered

- **Fold into the `penny` Typer CLI** — rejected: target resolution is dev
  tooling (neonctl, branch hygiene), not app code, and it needs env already
  set to run (circular).
- **Per-target scripts (`db-test.sh` / `db-prod.sh`)** — rejected: shallow;
  duplicates env loading/banner/resolution logic across two files.
