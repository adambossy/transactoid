# Expand `execute_shell_command` Policy (including `mv`, `cp`, `tree`)

## Summary
Replace the old read-only policy with a scoped read/create/update/move/copy policy for `execute_shell_command`, and log every blocked command in a copy/paste-friendly format.

## Locked Behavior
- Remove `is_command_allowed` entirely.
- Use `evaluate_command_policy(command)` as the single policy path.
- Allow commands: `pwd`, `ls`, `find`, `cat`, `head`, `tail`, `grep`, `rg`, `sed`, `echo`, `printf`, `touch`, `mkdir`, `mv`, `cp`, `tree`.
- Keep blocked: `rm`, `rmdir`, `chmod`, `chown`, `ln`, `dd`, `truncate`, `tee`, package managers.
- Allow `bash -c "<inner>"` only when `<inner>` is a single allowed command (no chaining/scripting operators).
- Writes/moves/copies remain scoped to skills + `memory/` only.

## Enforcement Rules
- For `cp`/`mv`: both source and destination paths must be inside allowed roots.
- For redirection (`>` / `>>`): allowed only for write-capable commands and only to allowed roots.
- For reads: paths must still be inside allowed roots.
- `tree` is read-only and allowed within allowed roots.

## Logging Requirement
On every blocked command, log one single-line entry:
- Prefix: `BLOCKED_EXECUTE_SHELL_COMMAND`
- JSON payload with:
  - `runtime`, `reason`, `base_command`, `operation`, `command`, `effective_command`, `policy`

This goes to existing ACP log output (typically `/tmp/transactoid.log` in the CLI path).

## Files to Change
- `src/transactoid/core/runtime/skills/policy.py`
- `src/transactoid/core/runtime/skills/filesystem_tool_gemini.py`
- `src/transactoid/core/runtime/skills/filesystem_tool_openai.py`
- `src/transactoid/core/runtime/gemini_runtime.py` (tool docstring text)

## Tests
- Update `tests/core/runtime/skills/test_policy.py` to target `evaluate_command_policy` only.
- Add coverage for:
  - allowed `mv`, `cp`, `tree`
  - `cp`/`mv` denied when either path is outside allowed roots
  - allowed `bash -c "echo ... >> memory/..."`
  - blocked chained `bash -c`
  - blocked-command log emission in Gemini/OpenAI filesystem tool tests

## Verification
1. `uv run ruff check .`
2. `uv run ruff format .`
3. `uv run mypy --config-file mypy.ini .`
4. `uv run deadcode .`
5. `uv run pytest -q`

## Assumptions
- `mv`/`cp` are allowed only within scoped roots; no cross-boundary moves/copies.
- `rm` remains blocked for now.
