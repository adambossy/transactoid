# Textual TUI Migration Plan

## Overview

Migrate the current Transactoid CLI agent from a print-based terminal interface to a Textual TUI application, preserving all current functionality (streaming output, tool calls, tool results, user input, color coding) while enabling future interactive features like collapsible elements.

---

## Part 1: Migration Plan

### 1.1 Architecture Overview

**New module layout:**

```
ui/
├── __init__.py
├── base_renderer.py    # Abstract renderer interface
├── cli_renderer.py     # Current StreamRenderer (moved here)
├── tui_renderer.py     # New Textual renderer implementation
├── app.py              # Textual TransactoidApp definition
└── widgets.py          # Shared widgets (later: collapsible ToolResult)
```

**Core Textual objects:**

- `TransactoidApp(App)` – main application
  - Creates and holds a `TransactoidSession`
  - Owns the main widgets
  - Wires input submission to `session.run_turn`
- Widgets:
  - `Header`, `Footer` (standard Textual)
  - `Log` / `RichLog` for streaming output
  - `Input` (single-line) for user commands
  - `VerticalScroll` / `Container` for layout
  - (Later) `ToolResultWidget` for collapsible tool results

**Key idea:** `EventRouter` and the agent remain unchanged; only the renderer swaps from `StreamRenderer` (prints) to `TextualRenderer` that calls `log.write()`.

---

### 1.2 Migration Steps

#### Step 0: Isolate Current CLI Loop (non-breaking refactor)

**Goal:** Make current CLI entrypoint reusable by both CLI and TUI.

1. Extract agent/session creation into a factory:

```python
# transactoid.py

def create_transactoid_session() -> TransactoidSession:
    # (existing code that defines run_sql, sync_transactions, etc.)
    agent = Agent(
        name="Transactoid",
        instructions=instructions,
        model="gpt-5.1",
        tools=[...],
        model_settings=ModelSettings(reasoning_effort="medium", summary="detailed"),
    )
    return TransactoidSession(agent)
```

2. Wrap the CLI loop in a function:

```python
def run_cli() -> None:
    session = create_transactoid_session()
    print("Transactoid Agent - Personal Finance Assistant")
    print("Type 'exit' or 'quit' to end the session.\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            renderer = StreamRenderer()
            router = EventRouter(renderer)
            asyncio.run(session.run_turn(user_input, renderer, router))
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
```

---

#### Step 1: Introduce Base Renderer Interface

**Goal:** Make it easy to swap CLI vs TUI renderers.

Create `ui/base_renderer.py`:

```python
from typing import Any
from agents.items import MessageOutputItem

class BaseRenderer:
    def begin_turn(self, user_input: str) -> None: ...
    def on_reasoning(self, delta: str) -> None: ...
    def on_output_text(self, delta: str) -> None: ...
    def on_tool_call_started(self, call_id: str, name: str) -> None: ...
    def on_tool_arguments_delta(self, call_id: str, delta: str) -> None: ...
    def on_tool_call_completed(self, call_id: str) -> None: ...
    def on_tool_result(self, output: Any) -> None: ...
    def on_message_output(self, item: MessageOutputItem) -> None: ...
    def on_unknown(self, event: Any) -> None: ...
    def end_turn(self, result: Any | None) -> None: ...
```

Update `StreamRenderer` to subclass `BaseRenderer` and move to `ui/cli_renderer.py`.

Update `EventRouter` to depend on `BaseRenderer`:
```python
EventRouter.__init__(self, renderer: BaseRenderer) -> None:
```

---

#### Step 2: Implement TransactoidApp (basic TUI skeleton)

**Goal:** Have a Textual app shell that uses the same `TransactoidSession`.

Create `ui/app.py`:

```python
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Log
from textual.containers import Vertical

from transactoid import create_transactoid_session
from .tui_renderer import TextualRenderer
from transactoid import EventRouter

class TransactoidApp(App):
    CSS_PATH = "transactoid.tcss"  # optional

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = create_transactoid_session()
        self.log = None
        self.input = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            self.log = Log(id="log", highlight=True, wrap=True)
            yield self.log
            self.input = Input(placeholder="You: ", id="input")
            yield self.input
        yield Footer()

    async def on_mount(self) -> None:
        await self.input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return
        if user_input.lower() in ("exit", "quit"):
            await self.action_quit()
            return

        event.input.value = ""  # clear input box

        renderer = TextualRenderer(self.log)
        router = EventRouter(renderer)

        self.call_later(self.run_turn_async, user_input, renderer, router)

    async def run_turn_async(self, user_input, renderer, router):
        await self.session.run_turn(user_input, renderer, router)
```

Optional CSS (`transactoid.tcss`):

```css
#main {
    layout: vertical;
}

#log {
    height: 1fr;
}

#input {
    dock: bottom;
}
```

---

#### Step 3: Implement TextualRenderer

**Goal:** Preserve all current behavior but write to a log widget instead of stdout.

Create `ui/tui_renderer.py`:

```python
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from textual.widgets import Log
from agents.items import MessageOutputItem

from .base_renderer import BaseRenderer

class JsonEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class ToolCallState:
    def __init__(self, call_id: str, name: str) -> None:
        self.call_id = call_id
        self.name = name
        self.args_chunks: list[str] = []

    def args_text(self) -> str:
        return "".join(self.args_chunks)

class TextualRenderer(BaseRenderer):
    def __init__(self, log: Log) -> None:
        self.log = log
        self.tool_calls: dict[str, ToolCallState] = {}
        self._thinking_shown = False

    def begin_turn(self, user_input: str) -> None:
        self.log.write("")

    def on_reasoning(self, delta: str) -> None:
        self.log.write(delta, style="yellow")

    def on_output_text(self, delta: str) -> None:
        self.log.write(delta, style="green")

    def on_tool_call_started(self, call_id: str, name: str) -> None:
        self.tool_calls[call_id] = ToolCallState(call_id, name)

    def on_tool_arguments_delta(self, call_id: str, delta: str) -> None:
        state = self.tool_calls.get(call_id)
        if not state:
            state = ToolCallState(call_id, "unknown")
            self.tool_calls[call_id] = state
        state.args_chunks.append(delta)

    def on_tool_call_completed(self, call_id: str) -> None:
        state = self.tool_calls.get(call_id)
        if not state:
            return
        args_text = state.args_text()
        if not args_text:
            self.log.write(f"📞 {state.name}()", style="cyan")
        else:
            try:
                args = json.loads(args_text)
                if state.name == "run_sql" and "query" in args:
                    query = args.pop("query")
                    args_str = json.dumps(args) if args else "{}"
                    self.log.write(f"📞 {state.name}({args_str})", style="cyan")
                    self.log.write("SQL:", style="magenta")
                    self.log.write(query, style="magenta")
                else:
                    args_str = json.dumps(args, cls=JsonEncoder)
                    self.log.write(f"📞 {state.name}({args_str})", style="cyan")
            except json.JSONDecodeError:
                self.log.write(f"📞 {state.name}({args_text})", style="cyan")
        self.log.write("")

    def _summarize_tool_result(self, output: Any) -> str:
        if not isinstance(output, dict):
            text = str(output)
            return text[:60] + "..." if len(text) > 60 else text

        parts = []
        if "status" in output:
            parts.append(output["status"])
        if "error" in output:
            error_text = str(output["error"])[:40]
            parts.append(f"error: {error_text}...")
        if "accounts" in output:
            parts.append(f"{len(output['accounts'])} accounts")
        if "count" in output:
            parts.append(f"{output['count']} rows")
        if "total_added" in output:
            parts.append(f"+{output['total_added']} txns")
        if "message" in output and "status" not in output:
            msg = output["message"][:40]
            parts.append(msg)

        return ", ".join(parts) if parts else "{...}"

    def on_tool_result(self, output: Any) -> None:
        summary = self._summarize_tool_result(output)
        self.log.write(f"↩️ Tool result ▶ {summary}", style="blue")
        self.log.write("")

    def on_message_output(self, item: MessageOutputItem) -> None:
        pass  # Handled by on_output_text

    def on_unknown(self, event: Any) -> None:
        pass

    def end_turn(self, result: Any | None) -> None:
        self.log.write("")
        self.log.write("")
        if result is not None:
            raw_responses = getattr(result, "raw_responses", None)
            if raw_responses:
                self.log.write("=== TOKEN USAGE ===", style="bold")
                for raw in raw_responses:
                    usage = getattr(raw, "usage", None)
                    if usage:
                        self.log.write(str(usage))
```

**Color mapping:**
- `"reason"` → `"yellow"`
- `"text"` → `"green"`
- `"tool"` → `"cyan"`
- `"args"` → `"magenta"`
- `"out"` → `"blue"`
- `"error"` → `"red"`
- `"faint"` → `"dim"`

---

#### Step 4: Switch Entrypoint to TUI

Update `transactoid.py` main block:

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        from ui.app import TransactoidApp
        TransactoidApp().run()
```

---

### 1.3 Risks and Guardrails

| Risk | Guardrail |
|------|-----------|
| Blocking Textual event loop during `session.run_turn` | Run in background task (`call_later`, `run_worker`, or `create_task`) |
| User submits input while turn is running | Disable input widget until `end_turn` is called |
| Colors not readable in some terminals | Keep styles simple (green/yellow/cyan/red) |
| Log growth in long sessions | Acceptable for now; add truncation later if needed |

---

## Part 2: Collapsible Tool Results Requirements

*To be implemented after the Textual migration is complete.*

### 2.1 Functional Requirements

1. **Default collapsed**
   - Tool results appear as a single-line summary
   - Leading icon: `▶`
   - Text: summary string from `_summarize_tool_result`
   - Style: consistent with current tool result color (blue)
   - Full JSON is **not visible** initially

2. **Expandable on click/activation**
   - Interactions that toggle expand/collapse:
     - **Mouse:** clicking anywhere on the summary row
     - **Keyboard:** focus the row (Tab/Arrow keys) and press `Enter` or `Space`
   - On expand:
     - Icon changes to `▼`
     - Child view appears underneath with full JSON (pretty-printed, optionally syntax highlighted)
   - On collapse:
     - Icon changes back to `▶`
     - JSON block is hidden

3. **Visual state indicators**
   - Expanded state: may use different background color or bold summary text
   - Collapsed state: neutral
   - Scroll position should remain reasonable (no jarring jumps)

4. **Multiple tool results**
   - Each tool result has independent expanded/collapsed state
   - No accordion behavior required (expanding one doesn't collapse others)

5. **Persistence in-session**
   - States persist for app duration
   - New streaming output doesn't affect existing expanded/collapsed states

6. **Summary content**
   - Use existing `_summarize_tool_result` logic
   - Truncate very long summaries with "…"

### 2.2 Non-Functional / UX Requirements

1. **Keyboard accessibility**
   - Rows must be focusable via keyboard navigation
   - Use Textual's focus system (`can_focus=True`)
   - `Enter`/`Space` toggles expanded state
   - Focus stays on summary row when toggling

2. **Performance**
   - Large JSON payloads: pretty-print once, then show/hide on toggle
   - Expected scale: < 100 tool results per session (no virtualization needed)

3. **Error handling**
   - If JSON serialization fails: show fallback raw string with label "(raw tool output)"
   - If output is not a dict: display `repr(output)` as expanded content

### 2.3 Implementation Approach

Create `ToolResultWidget` in `ui/widgets.py`:

```python
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Static
import json
from typing import Any

class ToolResultWidget(Widget, can_focus=True):
    DEFAULT_CSS = """
    ToolResultWidget {
        layout: vertical;
    }
    .summary {
        color: blue;
    }
    .summary:focus {
        text-style: bold;
    }
    .details {
        color: grey70;
    }
    """

    def __init__(self, summary: str, full_output: Any, **kwargs):
        super().__init__(**kwargs)
        self.summary_text = summary
        self.full_output = full_output
        self.expanded = False
        self._details_text = self._format_output(full_output)

    def _format_output(self, output: Any) -> str:
        try:
            return json.dumps(output, indent=2, sort_keys=True)
        except TypeError:
            return repr(output)

    def compose(self) -> ComposeResult:
        icon = "▶" if not self.expanded else "▼"
        self.summary = Static(f"{icon} {self.summary_text}", classes="summary")
        self.details = Static("", classes="details")
        yield self.summary
        yield self.details

    def toggle(self) -> None:
        self.expanded = not self.expanded
        icon = "▼" if self.expanded else "▶"
        self.summary.update(f"{icon} {self.summary_text}")
        if self.expanded:
            self.details.update(self._details_text)
        else:
            self.details.update("")

    def on_click(self, event) -> None:
        self.toggle()

    def key_enter(self) -> None:
        self.toggle()

    def key_space(self) -> None:
        self.toggle()
```

**Integration path:**

- **Phase 1:** Migrate to Textual using `Log` (this plan)
- **Phase 2:** Introduce structured messages pane, render tool results with `ToolResultWidget`
- **Phase 3 (optional):** Replace plain log output with structured widgets for all event types

---

## Effort Estimates

| Task | Effort |
|------|--------|
| Step 0: Isolate CLI loop | S (< 1h) |
| Step 1: Base renderer interface | S (< 1h) |
| Step 2: TransactoidApp skeleton | M (1-2h) |
| Step 3: TextualRenderer implementation | M (1-2h) |
| Step 4: Switch entrypoint | S (< 1h) |
| **Total migration** | **M (4-6h)** |
| Collapsible tool results (post-migration) | M (1-3h) |

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project.dependencies]
textual = ">=0.50.0"
```
