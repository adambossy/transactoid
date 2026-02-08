# Core Runtime Multi-Provider Implementation Plan

1. Add provider-agnostic runtime protocol (`CoreRuntime`, `CoreSession`, canonical events/results).
2. Add runtime config + factory with startup/provider validation and fail-fast behavior.
3. Implement shared tool invoker and OpenAI runtime with canonical event mapping.
4. Add Claude and Gemini runtime modules as thin-adapter scaffolds that fail fast when selected without SDK wiring.
5. Refactor `Transactoid` orchestrator to build `ToolRegistry` once and expose `create_runtime` while preserving `create_agent` compatibility for now.
6. Migrate ACP, Report runner, Evals, and ChatKit server to depend on `CoreRuntime` instead of direct SDK Runner/Agent usage.
7. Add/adjust tests around runtime protocol usage in ACP prompt handler.
8. Run required checks: ruff check/format, mypy, deadcode, pytest.
