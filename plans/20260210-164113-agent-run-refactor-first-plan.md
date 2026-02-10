# Refactor-First Plan: Core `agent_run` Service + Thin CLI

## Summary
Make `cli.py` a thin adapter. Move all run/report orchestration into core modules first, then add `agent-run` on top of that core service. `report` becomes a compatibility alias that calls the same core path with preset inputs.

## Core Structural Changes (Prerequisite)

1. Create a new core package for run orchestration:
   - `src/transactoid/services/agent_run/`
   - `src/transactoid/services/agent_run/types.py`
   - `src/transactoid/services/agent_run/service.py`
   - `src/transactoid/services/agent_run/pipeline.py`
   - `src/transactoid/services/agent_run/email.py` (or reuse existing service module if cleanly shared)
   - `src/transactoid/services/agent_run/html.py` (generic md/text -> html wrapper)

2. Move thick report logic out of `src/transactoid/ui/cli.py`:
   - `_report_impl`, `_upload_report_artifacts`, email/output orchestration, and runner wiring all migrate into `AgentRunService`.
   - `cli.py` only parses flags, builds request DTO, invokes service, prints result.

3. Keep `src/transactoid/jobs/report/` as compatibility wrapper only:
   - Either minimal re-exports or small adapter that maps old report semantics to `AgentRunService`.
   - No business logic should remain there once refactor is complete.

## Public Interfaces

### New command
`transactoid agent-run` with:
1. `--prompt` or `--prompt-key`
2. `--continue <run-id>`
3. repeatable `--email`
4. `--save-md/--no-save-md`
5. `--save-html/--no-save-html`
6. repeatable `--output-target r2|local` (default `r2`)
7. `--local-dir` (default hidden dir, gitignored)
8. `--max-turns`
9. optional `--month` helper for spending-report template compatibility

### Existing command
`transactoid report`:
1. stays available,
2. delegates to `AgentRunService` with preset `prompt_key=spending-report` and existing default behavior,
3. no direct orchestration logic in CLI.

## Service Responsibilities (Decision-Complete)

`AgentRunService` handles:
1. prompt resolution (`prompt` vs `prompt_key`)
2. template variable injection
3. agent execution
4. trace persistence and continuation (R2 trace artifact model)
5. markdown/html artifact generation
6. target fanout (`r2`, `local`)
7. email send
8. run manifest creation

`cli.py` handles:
1. input validation
2. request object construction
3. service call
4. user-facing output and exit codes only

## R2 Trace + Continuation

1. Persist run trace as `agent-runs/<run-id>/trace.sqlite3`.
2. Persist run manifest as `agent-runs/<run-id>/manifest.json`.
3. Continue flow:
   - download prior trace via manifest from run-id,
   - resume with same session_id,
   - publish new run-id with `parent_run_id`.

## Tests

1. `tests/services/agent_run/test_service.py`
   - happy path for `prompt` and `prompt_key`
   - continuation from `run-id`
   - error handling + manifest writing
2. `tests/services/agent_run/test_pipeline.py`
   - md/html toggles
   - output target combinations
   - local directory behavior
3. `tests/adapters/storage/test_r2.py`
   - add download coverage for trace/manifest fetch
4. `tests/ui/test_cli_agent_run.py`
   - CLI parsing/validation only
   - verifies CLI delegates to service
5. `tests/ui/test_cli_report_alias.py`
   - verifies `report` delegates to `AgentRunService` with spending-report defaults

## Assumptions / Defaults

1. `agent-run` is the canonical orchestration path.
2. `report` is compatibility-only alias.
3. Default output target is `r2`.
4. Default formats are md + html.
5. Default local path is hidden directory (added to `.gitignore`).
6. Recurring jobs are defined directly as Fly cron commands (`--prompt-key ...`), not a prompt-job registry file.
