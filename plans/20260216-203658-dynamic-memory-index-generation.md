# Dynamic memory index generation

## Summary
- Generate `memory/index.md` from live `memory/` contents at runtime.
- Store generator prompt in Promptorium under `generate-memory-index`.
- Add a runtime tool to regenerate the index on demand.
- Add a shared startup hook used by orchestrator and MCP startup.
- Add a Gemini verification script with semantic similarity judging.

## Implementation steps
1. Add `transactoid.memory.index_generation` service for tree scan, Gemini generation, and hash-gated file sync.
2. Add `transactoid.bootstrap.initialization` hook module with process-local idempotency.
3. Wire hook into `Transactoid.__init__` and `ui/mcp/server.py` global startup path.
4. Register `generate_memory_index` in runtime tool registry.
5. Add Promptorium prompt files + metadata entry for `generate-memory-index`.
6. Add `scripts/verify_memory_index_generation.py` for generation + semantic judge verification.
7. Update/add tests for memory generation and initialization behavior.
8. Run lint, format, mypy, deadcode, and pytest.
