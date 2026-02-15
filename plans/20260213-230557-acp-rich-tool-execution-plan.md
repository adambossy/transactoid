## Rich ACP Tool Execution Payloads (Visual-Equivalent to Screenshot)

### Summary
Implement end-to-end rich tool-call emission for ACP so clients display command/input, named outputs, and final results in the same visual structure as the screenshot.  
Scope is **OpenAI + Gemini** runtimes, with a **stable Transactoid schema** (not codex wire clone), and dual output strategy: **`rawInput/rawOutput` + rendered `content`**.

### Public Interface Changes
1. Extend ACP notifier payload support.
- File: `src/transactoid/ui/acp/notifier.py`
- `tool_call(...)` gains optional:
  - `raw_input: dict[str, Any] | None`
  - `content: list[dict[str, Any]] | None`
  - `locations: list[dict[str, Any]] | None`
- `tool_call_update(...)` gains optional:
  - `raw_output: dict[str, Any] | None`
  - `content: list[dict[str, Any]] | None` (already present, keep)
  - `title: str | None`, `kind: ToolCallKind | None`, `locations: ...` (optional passthrough)
- Behavior: omit keys when value is `None`.

2. Extend runtime event contract for structured tool execution data.
- File: `src/transactoid/core/runtime/protocol.py`
- Add typed event payload models:
  - `ToolCallInputEvent` (call_id, tool_name, arguments, runtime_info)
  - `ToolCallOutputEvent` (call_id, status, output, runtime_info, named_outputs)
- Keep existing events for backward compatibility while migrating handler logic.
- Add canonical helper types:
  - `NamedOutput` (`name`, `mime_type`, `text`)
  - `ToolRuntimeInfo` (`command`, `cwd`, `streams`, `exit_code`, etc. as optional fields)

3. Introduce ACP rich payload formatter module.
- New file: `src/transactoid/ui/acp/tool_payloads.py`
- Responsibilities:
  - Build stable `rawInput/rawOutput` envelopes.
  - Build user-visible `content` blocks (markdown/text) that match screenshot-like layout.
  - Normalize dict/str outputs across runtimes.
- Canonical envelope shape:
  - `rawInput`: `{ "schema": "transactoid.tool_call.input.v1", "tool": ..., "arguments": ..., "runtime": ... }`
  - `rawOutput`: `{ "schema": "transactoid.tool_call.output.v1", "status": ..., "result": ..., "namedOutputs": [...], "runtime": ... }`

### Implementation Plan

1. Upgrade runtime event production (OpenAI + Gemini).
- `src/transactoid/core/runtime/openai_runtime.py`
  - Capture tool start info from function-call added events.
  - Accumulate arguments deltas to finalized arguments JSON.
  - Capture output payload from `ToolCallOutputItem`.
  - Emit structured input/output events with runtime metadata where available.
- `src/transactoid/core/runtime/gemini_runtime.py`
  - Emit structured input from `function_call` name/args.
  - Emit structured output from `function_response`.
  - Map success/failure using existing status heuristics.
- Preserve existing final text streaming behavior unchanged.

2. Refactor prompt handler to stateful tool lifecycle assembly.
- `src/transactoid/ui/acp/handlers/prompt.py`
- Maintain per-call state map keyed by `call_id`:
  - started payload, args, current status, latest output, rendered sections.
- On start:
  - send `tool_call` with `pending`, `rawInput`, and initial rendered `content`.
- On progress:
  - send `tool_call_update` with `in_progress` and incremental `content` (if meaningful).
- On completion/failure:
  - send final `tool_call_update` with status + `rawOutput` + final rendered `content`.
- Keep `agent_message_chunk` and `agent_thought_chunk` logic unchanged.

3. Ensure rendered content is screenshot-equivalent in structure.
- Build content sections in deterministic order:
  1. Tool/command header
  2. Input/arguments block
  3. Named outputs (stdout/stderr/result/etc.)
  4. Final status/result summary
- Use ACP content block shape expected by Toad:
  - `[{ "type": "content", "content": { "type": "text", "text": "..." } }]`

4. Keep adapter path compatible.
- `src/transactoid/adapters/acp_adapter.py`
- Optionally route through shared formatter helpers so adapter-emitted tool calls match runtime-emitted shape.
- If adapter path is not used by ACP server flow, keep minimal compatibility update only (no behavior divergence).

5. Logging and observability updates.
- `src/transactoid/ui/acp/logger.py`
- Add logs for:
  - tool payload build success/fallback
  - missing fields and normalization fallbacks
  - per-call lifecycle transitions with call_id

### Edge Cases and Failure Modes
1. Missing/unknown `call_id`.
- Fallback to generated stable ID and log warning.
2. Non-JSON-parseable args deltas.
- Preserve raw string in `runtime.args_raw`; include parse error marker in `rawInput`.
3. Tool output is non-dict/non-str object.
- Stringify safely for rendered content; include serialized fallback in `rawOutput.result_text`.
4. Tool start without completion event.
- Emit timeout/finalization `failed` update at turn end for orphaned calls.
5. Completion before start (out-of-order events).
- Create synthetic start state and continue lifecycle.

### Test Plan

1. Unit tests: notifier payload shape.
- File: `tests/ui/acp/test_notifier.py`
- Add coverage for:
  - `rawInput` inclusion on `tool_call`
  - `rawOutput` inclusion on `tool_call_update`
  - omission of optional keys when `None`
  - mixed content + raw fields together

2. Unit tests: prompt handler lifecycle assembly.
- File: `tests/ui/acp/handlers/test_prompt.py`
- Cases:
  - tool start -> in_progress -> completed emits rich structured updates
  - failed tool emits `failed` with error result in raw/rendered outputs
  - multiple interleaved tool calls maintain correct call_id association
  - out-of-order events handled deterministically

3. Integration tests: full ACP flow.
- File: `tests/integration/test_acp_server.py`
- Validate JSON-RPC notification sequence and exact update payload structure for rich tool calls.

4. Runtime-specific tests.
- OpenAI: arguments delta accumulation and tool output mapping.
- Gemini: function_call/function_response mapping into canonical envelopes.

5. Verification gates to run.
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`

### Assumptions and Defaults
1. “Exactly like screenshot” is interpreted as **visual-equivalent layout**, not codex byte-for-byte schema.
2. Canonical rich schemas are versioned as:
- `transactoid.tool_call.input.v1`
- `transactoid.tool_call.output.v1`
3. Rich payload emission is enabled by default for ACP server prompts.
4. Existing plain text tool updates remain backward compatible via rendered `content`.
5. Claude runtime remains unchanged in this change set since it is currently unimplemented.
