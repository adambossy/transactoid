# Refactor `AgentRunService` to Use Env-Selected Runtime (Parity with `uv run transactoid`)

## Summary
Refactor the headless run path (`run` and `run-scheduled-report`) so runtime/provider selection is driven by the same env-based mechanism used by interactive runtime creation (`load_core_runtime_config_from_env()` + `Transactoid.create_runtime()`), instead of the legacy `create_agent()` OpenAI-only shim.

This fixes the current failure mode (`create_agent is only supported with OpenAI runtime`) and adds provider-agnostic continuation via transcript state persisted in R2.

## Scope and Goals
- Make `AgentRunService` choose runtime by env var exactly like the rest of the runtime stack.
- Remove OpenAI-only coupling in this path (`Agent` + `Runner.run` + `SQLiteSession` dependency).
- Implement cross-provider continuation using canonical transcript state in R2 JSON.
- Keep existing CLI behavior (`transactoid run`, `run-scheduled-report`) unchanged from user perspective.
- Enforce **atomic commits per phase**.

## Design Decisions (Locked)
- Runtime strategy: **Unified CoreRuntime path** for all providers.
- Continuation strategy: **Cross-provider transcript-level continuation**.
- Continuation persistence: **R2 JSON state** under `agent-runs/<run_id>/...`.
- Legacy trace-based continuation (`trace.sqlite3`) is not primary continuation source going forward.

## Implementation Plan (Phased + Atomic Commits)

### Phase 1: Runtime Selection Refactor
**Files**
- `src/transactoid/services/agent_run/service.py`
- `src/transactoid/orchestrators/transactoid.py` (only if small helper needed)

**Changes**
- Replace `_create_agent()` + `_run_agent()` (OpenAI `Runner`) with CoreRuntime flow:
  1. `runtime_config = load_core_runtime_config_from_env()`
  2. `runtime = Transactoid(...).create_runtime(runtime_config=runtime_config, sql_dialect=...)`
  3. `session = runtime.start_session(session_key)`
  4. `core_result = await runtime.run(input_text=..., session=session, max_turns=...)`
  5. `report_text = core_result.final_text`
  6. `await runtime.close()` in `finally`.

**Session key policy**
- New run: `session_key = run_id`.
- Continue run: `session_key = continue_run_id`.

**Atomic commit**
- Commit only runtime-selection refactor + tests directly covering this phase.

### Phase 2: Continuation State Model + R2 Storage
**Files**
- New: `src/transactoid/services/agent_run/state.py`
- Update: `src/transactoid/services/agent_run/types.py`
- Update: `src/transactoid/services/agent_run/__init__.py`

**New types**
- `ConversationTurn`
- `ContinuationState`

**Storage**
- `upload_continuation_state(run_id, state) -> ArtifactRecord`
- `download_continuation_state(run_id) -> ContinuationState`
- R2 key: `agent-runs/<run_id>/session-state.json`
- artifact type: `session-state`.

**Atomic commit**
- Commit only new types + state persistence + focused tests.

### Phase 3: Continuation Assembly + Service Integration
**Files**
- `src/transactoid/services/agent_run/service.py`
- Optional prompt template file (only if needed)

**Behavior**
- For `continue_run_id`, load prior `ContinuationState`, reconstruct bounded transcript context, append current prompt.
- On missing/corrupt state: return explicit failure.
- Persist `session-state.json` on successful run.
- Keep `manifest.json` behavior; trace no longer required for continuation.

**Atomic commit**
- Commit integration logic + continuation behavior tests.

### Phase 4: Observability + CLI Regression Hardening
**Files**
- `src/transactoid/services/agent_run/service.py`
- possibly `src/transactoid/ui/cli.py` for surfaced error text only

**Logs**
- Provider/model selected
- Continuation state load source (`continue_run_id`)
- State upload success/failure
- explicit continuation errors.

**Atomic commit**
- Commit logging/error-hardening + regression tests.

## Public API / Interface Changes
1. New R2 artifact:
- `agent-runs/<run_id>/session-state.json` (`session-state`, `application/json`).

2. New dataclasses:
- `ConversationTurn`
- `ContinuationState`

3. `AgentRunService` internal runtime execution changes:
- provider-agnostic CoreRuntime, no OpenAI-only dependency.

## Test Plan

### `tests/services/agent_run/test_service.py`
- `test_execute_uses_create_runtime_for_provider_from_env`
- `test_execute_with_gemini_provider_succeeds_when_core_runtime_returns_text`
- `test_execute_with_continue_loads_session_state_and_builds_continuation_input`
- `test_execute_continue_missing_state_returns_failure_with_clear_error`
- `test_execute_persists_session_state_artifact_on_success`

### `tests/services/agent_run/test_state.py` (new) and/or `test_trace.py`
- `ContinuationState` serialization/deserialization
- R2 key correctness
- malformed JSON handling.

### CLI/regression
- `run-scheduled-report` no longer fails with `create_agent is only supported with OpenAI runtime` when provider=gemini.

### Required verification commands (per phase before commit)
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`

## Rollout / Validation Loops

### Loop A: Gemini
1. Deploy with:
- `TRANSACTOID_AGENT_PROVIDER=gemini`
- `TRANSACTOID_AGENT_MODEL=gemini-3-flash-preview`
2. Trigger `run-scheduled-report`.
3. Confirm logs show provider/model selection and successful run completion.
4. Confirm `session-state.json` exists in R2 for new run ID.
5. Validate `--continue <run_id>` succeeds using that run’s state.

### Loop B: OpenAI
1. Deploy with:
- `TRANSACTOID_AGENT_PROVIDER=openai`
- `TRANSACTOID_AGENT_MODEL=gpt-5-mini-2025-08-07`
2. Trigger `run-scheduled-report`.
3. Confirm logs show provider/model selection and successful run completion.
4. Confirm `session-state.json` exists in R2 for new run ID.
5. Validate `--continue <run_id>` succeeds using that run’s state.

## Commit Strategy (Explicit)
- **Commit 1 (Phase 1):** runtime selection refactor.
- **Commit 2 (Phase 2):** continuation types + R2 state storage.
- **Commit 3 (Phase 3):** continuation integration and behavior.
- **Commit 4 (Phase 4):** observability and CLI regression hardening.
- Each commit must be independently coherent, tested, and leave repository in a working state.

## Assumptions and Defaults
- Continuation is transcript-level (not provider-native hidden-state replay).
- `session-state.json` is canonical continuation source.
- Older runs without state artifact may not be continuable.
- Runtime selection source of truth remains `load_core_runtime_config_from_env()`.
