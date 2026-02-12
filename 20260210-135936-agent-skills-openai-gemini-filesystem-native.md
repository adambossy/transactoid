# Plan: Filesystem-Native Agent Skills for OpenAI and Gemini (Claude Native)

## Summary
Implement Claude-style skills for Transactoid core runtimes by making skills discoverable through filesystem navigation (not skill-specific tools).
Skills are always enabled. No max auto-load limit.
Claude uses native SDK behavior; OpenAI and Gemini get equivalent behavior by exposing filesystem-capable tooling to the model.

## Final Scope
1. Remove skill feature flags:
- No `skills_enabled`
- No `skills_max_auto_load`
- Skills are always on.
2. Remove skill discovery/load tools:
- No `list_skills` tool
- No `load_skill` tool
3. Use filesystem-native discovery:
- Model discovers and reads `SKILL.md` via FS tools.
4. Support three skill roots with precedence:
- Project: `.claude/skills`
- User: `~/.claude/skills`
- Built-in: `src/transactoid/skills`
5. Claude runtime uses native Claude skills semantics (when Claude runtime is wired).

## API / Config Changes
Update `CoreRuntimeConfig` in `src/transactoid/core/runtime/config.py`:
- Keep only path config (no enable/max):
  - `skills_project_dir: str = ".claude/skills"`
  - `skills_user_dir: str = "~/.claude/skills"`
  - `skills_builtin_dir: str = "src/transactoid/skills"`

Add env vars:
- `TRANSACTOID_AGENT_SKILLS_PROJECT_DIR`
- `TRANSACTOID_AGENT_SKILLS_USER_DIR`
- `TRANSACTOID_AGENT_SKILLS_BUILTIN_DIR`

No protocol signature changes to `CoreRuntime`.

## Provider-Specific Runtime Design

### 1) Claude
- Keep behavior native to Claude Agent SDK skills.
- Runtime wiring (when `ClaudeCoreRuntime` is implemented):
  - Enable skills with SDK settings (`setting_sources=["project","user"]` and tool permissions including `Skill`).
  - Allow filesystem tools needed for reading skill files as part of Claude’s native stack.
- No custom emulation layer.

### 2) OpenAI
- OpenAI runtime must expose filesystem-capable tools so model can discover skills from disk.
- Preferred implementation: OpenAI Agents SDK local shell capability (`ShellTool` / local shell executor).
- Runtime guardrails:
  - Read-only command allowlist: `pwd`, `ls`, `find`, `rg --files`, `rg`, `cat`, `sed -n`
  - Block mutating commands (`rm`, `mv`, `cp`, redirection writes, package installs, etc.).
  - Path allowlist rooted to configured skill dirs.
- Add instruction block telling model where skills live and how to inspect `SKILL.md` directly.

### 3) Gemini
- Gemini runtime must expose equivalent filesystem capabilities (Gemini ADK does not auto-browse local files by default).
- Implementation options in code path (choose one and standardize):
  - ADK function tools for filesystem read/list/glob/search, or
  - ADK MCP toolset backed by filesystem server.
- Enforce same read-only + path allowlist policy as OpenAI.
- Add same instruction block for skill directory locations and usage.

## Core Runtime Changes

### A) New shared module: `src/transactoid/core/runtime/skills/`
1. `paths.py`
- Resolve/expand skill roots.
- Normalize absolute paths.
- Validate directories exist (non-fatal if missing).
2. `prompting.py`
- Inject compact “Skill locations and usage protocol” into instructions:
  - Search skill dirs
  - Read relevant `SKILL.md`
  - Follow instructions from loaded skills
  - Prefer project/user over built-in when duplicates exist
3. `policy.py`
- Shared read-only command + path policy used by OpenAI/Gemini FS tools.

### B) Orchestrator wiring
Update `src/transactoid/orchestrators/transactoid.py`:
- During `create_runtime()`, resolve skill paths and inject FS-skill usage guidance into instructions.
- No skill registration in `ToolRegistry` (discovery is filesystem-native).

### C) Runtime wiring
1. `src/transactoid/core/runtime/openai_runtime.py`
- Add filesystem navigation capability via OpenAI tooling with shared policy constraints.
2. `src/transactoid/core/runtime/gemini_runtime.py`
- Add filesystem navigation capability via ADK tooling/MCP with the same constraints.
3. `src/transactoid/core/runtime/claude_runtime.py`
- Leave scaffold behavior as-is for now, but document exact native skill settings to apply when implementing.

## Behavior Rules (Decision Complete)
1. Skills are discovered only by reading filesystem contents.
2. Agent must inspect `SKILL.md` before applying a skill.
3. Duplicate skill names resolve by precedence:
- Project > User > Built-in
4. Missing skill directories are non-fatal.
5. No persistent cache required in v1.
6. Explicit user references (`$SkillName` or exact name) are handled through instruction hinting only; model still performs FS lookup itself.

## Security / Safety Constraints
1. Filesystem capabilities must be read-only.
2. Access restricted to configured skill roots (plus safe traversal for discovery).
3. Deny command execution outside allowlist.
4. Return structured runtime/tool errors; never crash turn on missing skill files.

## Tests

### Unit tests
1. `tests/core/runtime/skills/test_paths.py`
- path expansion and normalization
- missing dirs handling
2. `tests/core/runtime/skills/test_prompting.py`
- deterministic instruction injection
- includes all three roots and precedence note
3. `tests/core/runtime/skills/test_policy.py`
- allowlist/denylist command checks
- path scope enforcement

### Runtime tests
1. `tests/core/runtime/test_openai_runtime.py` (new/extend)
- FS tool configured
- read-only policy applied
2. `tests/core/runtime/test_gemini_runtime.py` (new/extend)
- FS tool configured
- path policy applied

### Orchestrator tests
1. `tests/orchestrators/test_transactoid_skills_instructions.py`
- runtime instructions include skill location protocol and precedence.

## Documentation
1. Update `README.md` with:
- skill directory conventions
- provider behavior differences
- new env vars (path-only)
2. Add `docs/agent-skills.md`:
- how agents discover skills via filesystem
- provider wiring model
- safety constraints
- troubleshooting.

## Validation Checklist
Run:
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`

## Assumptions
1. Claude remains “native skills” and out-of-box once runtime is implemented.
2. OpenAI/Gemini require explicit filesystem tool wiring in core runtime for local skill discovery.
3. Skill count is small enough that no max auto-load limit is needed.
