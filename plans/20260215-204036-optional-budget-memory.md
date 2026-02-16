# Optional Budget Memory Injection Plan

## Goal
Add a single `memory/budget.md` file that is discoverable to the agent but not always injected in `{{AGENT_MEMORY}}`. Keep `memory/merchant-rules.md` always injected.

## Decisions
- Budget load strategy: agent on-demand
- Tree hint location: runtime-generated

## Implementation
1. Add `memory/budget.md`.
2. Update `memory/index.md` to document core-vs-optional memory behavior.
3. Refactor `src/transactoid/orchestrators/transactoid.py`:
   - Only auto-include `index.md` and `merchant-rules.md`
   - Generate and append runtime `memory/` tree hint
4. Update orchestrator tests for new assembly semantics and tree hint coverage.

## Validation
Run:
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`
