# Tax Returns Memory Local-Only Plan

## Goal
Add a `memory/tax-returns/` directory for user-provided tax-return context that is available to agent prompts but remains local-only by default.

## Decisions
- Files under `memory/tax-returns/` are included in memory assembly regardless of extension.
- Files ending with `.example` are excluded from prompt assembly.
- Only `memory/tax-returns/2026.md.example` is tracked in git.
- All other files in `memory/tax-returns/` are ignored.

## Implementation Targets
- `src/transactoid/orchestrators/transactoid.py`
- `tests/orchestrators/test_memory_assembly.py`
- `.gitignore`
- `memory/index.md`
- `README.md`
- `memory/tax-returns/2026.md.example`
