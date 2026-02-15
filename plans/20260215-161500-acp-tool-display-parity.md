# Plan: ACP Tool Display Parity with claude-code-acp

## Goal

Adopt claude-code-acp's tool identification, title generation, and output formatting patterns in transactoid's ACP layer — without coupling the ACP layer to any specific LLM provider or sacrificing the existing `CoreEvent` abstraction.

## What claude-code-acp does better

1. **Per-tool title formatting**: Titles are generated from actual arguments (e.g., `` `ls -la` `` for Bash, `Read src/main.py (1-50)` for Read, `grep -i "pattern" src/` for Grep), not generic labels.
2. **Tool kind granularity**: Uses `read`, `edit`, `execute`, `search`, `fetch`, `think` — transactoid only has `execute`, `fetch`, `edit`, `other`.
3. **Structured diff content**: Edit results emit `{type: "diff", path, oldText, newText}` blocks that clients can render as rich diffs.
4. **Output formatting per tool type**: Read results get markdown code fences with the correct language; Bash output is wrapped in `sh` fences; search results are presented as file lists; errors get code-fence wrapping.
5. **Location tracking**: File operations include `{path, line}` so clients can jump to source.

## What to preserve from transactoid

- **Provider-agnostic `CoreEvent` abstraction**: The ACP layer must not import or depend on any LLM SDK types.
- **Versioned raw envelopes**: `transactoid.tool_call.input.v1` / `output.v1` — the stable schema approach is better than claude-code-acp's pass-through of raw SDK content.
- **Orphan cleanup**: `_finalize_orphaned_calls` stays.
- **`ToolCallState` lifecycle**: The 5-phase lifecycle (started → args delta → input → completed → output) is needed for streaming providers.
- **Simplicity**: No `_meta` envelope, no hook callbacks, no permission model — these are Claude SDK-specific concerns.

## Design

### Core idea

Introduce a **`ToolPresenter`** module that maps `(tool_name, arguments, runtime_info)` → `(title, kind, content, locations)` for both input and output phases. This replaces the current `_generate_tool_title` method and the generic content builders in `tool_payloads.py`, while keeping the presenter at the ACP layer (not the runtime layer).

The presenter is a pure function module — no state, no side effects, no provider coupling. It receives the same `CoreEvent` data already available and returns display-ready payloads.

### New tool kinds

Add `search` and `read` to `ToolCallKind`:

```python
# Before
ToolCallKind = Literal["execute", "fetch", "edit", "other"]

# After
ToolCallKind = Literal["execute", "fetch", "edit", "read", "search", "other"]
```

This is purely a display hint for clients. It does not affect tool execution.

### New content block types

Add `diff` and `location` support to the content block vocabulary:

```python
# Diff content block (for file edits)
{"type": "diff", "path": "src/foo.py", "oldText": "...", "newText": "..."}

# Location metadata (for file operations)
{"path": "src/foo.py", "line": 42}
```

These are already part of the ACP spec (claude-code-acp and codex-acp both emit them). Transactoid just doesn't use them yet.

## Implementation steps

### Step 1: Extend `ToolCallKind` in `protocol.py`

**File**: `src/transactoid/core/runtime/protocol.py`

Add `"read"` and `"search"` to the `ToolCallKind` literal. Update `classify_tool_kind()`:

```python
ToolCallKind = Literal["execute", "fetch", "edit", "read", "search", "other"]

def classify_tool_kind(tool_name: str) -> ToolCallKind:
    kind_map: dict[str, ToolCallKind] = {
        "sync_transactions": "fetch",
        "run_sql": "execute",
        "recategorize_merchant": "edit",
        "tag_transactions": "edit",
        "list_accounts": "fetch",
        "list_plaid_accounts": "fetch",
        "scrape_amazon_orders": "fetch",
        "upload_artifact": "other",
        "migrate_taxonomy": "edit",
        "connect_new_account": "other",
    }
    return kind_map.get(tool_name, "other")
```

Also update `ToolCallKind` in `notifier.py` to match.

### Step 2: Create `ToolPresenter` module

**New file**: `src/transactoid/ui/acp/tool_presenter.py`

A pure-function module that generates display payloads per tool. This replaces `_generate_tool_title()` in `prompt.py` and the generic content builders in `tool_payloads.py`.

```python
@dataclass(frozen=True, slots=True)
class ToolDisplay:
    title: str
    kind: ToolCallKind
    content: list[dict[str, Any]]
    locations: list[dict[str, Any]]

def present_tool_input(
    tool_name: str,
    arguments: dict[str, Any],
    runtime_info: ToolRuntimeInfo | None = None,
) -> ToolDisplay:
    """Generate display payload for a tool call's input phase."""
    ...

def present_tool_output(
    tool_name: str,
    arguments: dict[str, Any],
    status: str,
    result: dict[str, Any] | str,
    named_outputs: list[NamedOutput] | None = None,
    runtime_info: ToolRuntimeInfo | None = None,
) -> ToolDisplay:
    """Generate display payload for a tool call's output phase."""
    ...
```

#### Input presentation rules (per tool)

| Tool | Title | Kind | Content | Locations |
|------|-------|------|---------|-----------|
| `run_sql` | First line of query, truncated to 60 chars | `execute` | Query in SQL code fence | — |
| `sync_transactions` | `"Sync up to {count} transactions"` | `fetch` | — | — |
| `recategorize_merchant` | `"Recategorize merchant {id} → {category}"` | `edit` | — | — |
| `tag_transactions` | `"Tag {n} transactions: {tags}"` | `edit` | — | — |
| `list_accounts` / `list_plaid_accounts` | `"List connected accounts"` | `fetch` | — | — |
| `connect_new_account` | `"Connect new bank account"` | `other` | — | — |
| `scrape_amazon_orders` | `"Scrape Amazon orders"` | `fetch` | — | — |
| `migrate_taxonomy` | `"{operation} {source_key}"` (e.g. `"Rename FOOD.DINING"`) | `edit` | Operation details as text | — |
| `upload_artifact` | `"Upload {artifact_type}"` | `other` | — | — |
| `execute_shell` | `` `{command}` `` | `execute` | Command text | Working directory if available |
| (unknown) | Tool name | `other` | Arguments as JSON code fence | — |

#### Output presentation rules (per tool)

| Tool | Content |
|------|---------|
| `run_sql` | Result rows as JSON code fence; on error, error text in code fence |
| `sync_transactions` | Summary text: `"Added {n}, modified {m}, removed {r}"` |
| `recategorize_merchant` | Summary: `"Recategorized {n} transactions"` |
| `tag_transactions` | Summary: `"Tagged {n} transactions"` |
| `list_accounts` / `list_plaid_accounts` | Account list as JSON |
| `execute_shell` | stdout in `sh` code fence; stderr appended if non-empty |
| `scrape_amazon_orders` | Summary: `"Scraped {n} orders, {m} items"` |
| (error) | Error text wrapped in code fence |
| (unknown) | Result as JSON code fence |

### Step 3: Update `tool_payloads.py`

**File**: `src/transactoid/ui/acp/tool_payloads.py`

- Keep `build_raw_input()` and `build_raw_output()` unchanged (versioned envelopes stay).
- Remove `build_rendered_content_input()` and `build_rendered_content_output()` — replaced by `ToolPresenter`.
- Keep `DatabaseJSONEncoder` (still needed by raw envelope builders).

### Step 4: Update `PromptHandler` to use `ToolPresenter`

**File**: `src/transactoid/ui/acp/handlers/prompt.py`

- Remove `_generate_tool_title()` method.
- In `_handle_tool_call_started()`: use `classify_tool_kind()` for the initial kind (already done).
- In `_handle_tool_call_input()`: call `present_tool_input()` instead of `_generate_tool_title()` + `build_rendered_content_input()`. Send the returned `title`, `kind`, `content`, and `locations`.
- In `_handle_tool_call_output()`: call `present_tool_output()` for rendered content. Continue using `build_raw_output()` for the raw envelope. Send `title`, `content`, and `locations` from the presenter alongside `raw_output` from the envelope builder.
- In `_handle_tool_call_completed()`: when sending a fallback input (args accumulated but no `ToolCallInputEvent` received), call `present_tool_input()` with the accumulated arguments.

### Step 5: Wire `locations` through the notifier

**File**: `src/transactoid/ui/acp/notifier.py`

The `tool_call()` and `tool_call_update()` methods already accept `locations` as an optional parameter and include it in the update dict. No changes needed unless locations need a fixed schema (currently `list[dict[str, Any]]`). Confirm the ACP spec shape is `{path: string, line?: number}` and document it.

### Step 6: Update tests

**Files**: `tests/test_tool_payloads.py`, `tests/test_prompt.py`

- Add tests for `tool_presenter.py`:
  - Each tool's input presentation (title, kind, content, locations).
  - Each tool's output presentation (content formatting).
  - Unknown tool fallback.
  - Edge cases: empty arguments, missing fields, very long SQL queries.
- Update existing `test_tool_payloads.py` to remove tests for deleted `build_rendered_content_input/output` functions.
- Update `test_prompt.py` to verify the new title/kind/content/locations flow through the handler.

### Step 7: Lint, type-check, format, dead code

Run all four checks and fix any issues:

```bash
uv run ruff check .
uv run ruff format .
uv run mypy --config-file mypy.ini .
uv run deadcode .
uv run pytest -q
```

## Out of scope

- **Permission model**: Transactoid tools are all auto-approved. No `canUseTool()` or `request_permission()`.
- **Plan mode / TodoWrite**: Not relevant — transactoid doesn't have a planning tool.
- **`_meta` envelope**: Claude SDK-specific; no equivalent needed.
- **Post-tool-use hooks**: Claude SDK-specific callback mechanism.
- **Session persistence**: Transactoid sessions are in-memory; no JSONL files.
- **Diff content for file edits**: Transactoid has no file-editing tools currently. The `ToolDisplay` dataclass supports diff content blocks so they can be added when file tools arrive.
- **Image content blocks**: Transactoid tools don't produce images.
- **Terminal streaming**: Transactoid has no interactive terminal tools. (The `execute_shell` tool runs to completion.)

## File change summary

| File | Change |
|------|--------|
| `core/runtime/protocol.py` | Extend `ToolCallKind` literal, update `classify_tool_kind()` |
| `ui/acp/notifier.py` | Update `ToolCallKind` import/literal to match |
| `ui/acp/tool_presenter.py` | **New file** — per-tool input/output display logic |
| `ui/acp/tool_payloads.py` | Remove `build_rendered_content_input/output`, keep raw envelope builders |
| `ui/acp/handlers/prompt.py` | Replace `_generate_tool_title` + content builders with `ToolPresenter` calls |
| `tests/test_tool_presenter.py` | **New file** — tests for presenter |
| `tests/test_tool_payloads.py` | Remove tests for deleted functions |
| `tests/test_prompt.py` | Update to verify new display fields |
