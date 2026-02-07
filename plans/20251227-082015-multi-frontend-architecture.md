# Multi-Frontend Architecture Refactoring Plan

> **Note**: This plan can be copied to `/Users/adambossy/code/transactoid/plans/` for version control after finalization.

## Executive Summary

Refactor Transactoid to support multiple frontends and integration modes while maintaining current functionality:

**High Priority Frontends**:
1. **OpenAI ChatKit** - Embeddable chat interface with Python backend
2. **MCP Server** - Expose tools via Model Context Protocol (Anthropic)
3. **Current CLI** - Maintain existing OpenAI Agents SDK integration

**Additional Frontends** (Architecture-ready, implement as needed):
4. **Web App UI** - React/Next.js chat interface using ChatKit.js
5. **Mobile App UI** - Mobile chat interface using ChatKit (or web view)
6. **Textual UI** - Terminal-based user interface (placeholder)

**Special Modes**:
7. **Headless Mode** - Run agent programmatically for evals/testing (no UI)
8. **Hex Integration** - Direct database access for Hex analytics platform

**Core Strategy**: Introduce Tool Protocol layer + Frontend Adapters without touching existing business logic.

**Key Principles**:
- Minimal invasive changes (wrapper pattern, not refactoring)
- Preserve streaming support for LLM responses
- Maintain strict type safety (mypy strict mode)
- All frontends have equal implementation priority

---

## Current Architecture

### Layers
```
CLI (ui/cli.py)
    ↓
Transactoid Orchestrator (orchestrators/transactoid.py)
    ↓ Direct instantiation + @function_tool wrappers
Tools: SyncTool, Categorizer, PersistTool
    ↓
Services: DB, Taxonomy, FileCache, PlaidClient
```

### Issues
- No standardized tool interface (each tool has different signatures)
- Tight coupling to OpenAI Agents SDK (@function_tool decorators)
- Inline tool instantiation in orchestrator
- Cannot easily expose tools through different frontends

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Frontend Layer                                      │
│                                                                                  │
│  ┌──────────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │   ChatKit Server │ │   MCP    │ │ Current  │ │ Headless │ │   Textual    │ │
│  │   (Backend)      │ │  Server  │ │   CLI    │ │   Mode   │ │     UI       │ │
│  └────────┬─────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│           │                 │             │             │               │        │
│  ┌────────┴────────┐        │             │             │               │        │
│  │                 │        │             │             │               │        │
│  │  ┌──────────┐  ┌▼────────▼────┐       │             │               │        │
│  │  │  Web App │  │  Mobile  App  │       │             │               │        │
│  │  │(ChatKit.js) │(ChatKit/View) │       │             │               │        │
│  │  └─────────────┴───────────────┘       │             │               │        │
│  │                                        │             │               │        │
│  │  (Web & Mobile connect as ChatKit clients)          │               │        │
│  │                                                      │               │        │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │                          Hex Analytics Platform                             │ │
│  │                    (Direct DB access via DATABASE_URL)                      │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
└───────────┼───────────────┼───────────────┼─────────────┼───────────────┼───────┘
            │               │               │             │               │
┌───────────┼───────────────┼───────────────┼─────────────┼───────────────┼───────┐
│           │     Adapter Layer             │             │               │       │
│  ┌────────▼────────┐  ┌──▼───────┐  ┌────▼─────────────▼───┐  ┌────────▼────┐ │
│  │    ChatKit      │  │   MCP    │  │   OpenAI Adapter     │  │   Textual   │ │
│  │    Adapter      │  │ Adapter  │  │  (CLI + Headless)    │  │   Adapter   │ │
│  └────────┬────────┘  └──┬───────┘  └────┬─────────────────┘  └────────┬────┘ │
└───────────┼───────────────┼───────────────┼────────────────────────────┼───────┘
            └───────────────┴───────────────┴────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────────────┐
│                     Tool Registry + Tool Protocol                                 │
│  - Standardized Tool interface (Protocol)                                        │
│  - ToolRegistry: register, lookup, execute                                       │
│  - Supports both: direct tool calls (API) and agent-mediated calls (ChatKit/CLI)│
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────────────┐
│                    Tool Wrappers (Implement Protocol)                             │
│  - SyncTransactionsTool, RecategorizeTool, TagTransactionsTool, RunSQLTool       │
│  - Delegate to existing tool implementations                                     │
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────────────┐
│                        Existing Tools (UNCHANGED)                                 │
│  - SyncTool, Categorizer, PersistTool                                            │
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────────────┐
│                         Services (UNCHANGED)                                      │
│  - DB, Taxonomy, FileCache, PlaidClient                                          │
│  - Direct access by: Hex (DB), API (all services), Headless mode (all services) │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Tool Protocol Foundation (Week 1)

#### 1.1 Define Tool Protocol
**File**: `tools/protocol.py`

Create standardized interface using Python Protocol:
- `Tool` protocol with: `name`, `description`, `input_schema`, `execute(**kwargs)`
- `ToolInputSchema` TypedDict for JSON Schema representation
- `@runtime_checkable` for runtime type validation

#### 1.2 Create Base Implementation
**File**: `tools/base.py`

`StandardTool` base class that:
- Implements Tool protocol
- Provides common execute() logic
- Delegates to `_execute_impl(**kwargs)` in subclasses

#### 1.3 Create Tool Registry
**File**: `tools/registry.py`

`ToolRegistry` class with:
- `register(tool)` - Add tool to registry
- `get(name)` - Lookup tool by name
- `all()` - Get all registered tools
- `execute(name, **kwargs)` - Execute tool by name

---

### Phase 2: Wrap Existing Tools (Week 2)

**Strategy**: Create protocol-compliant wrappers WITHOUT modifying existing tools.

#### 2.1 SyncTransactionsTool
**File**: `tools/sync/sync_tool.py`

```python
# Keep existing SyncTool class unchanged
class SyncTool:
    """Original implementation (unchanged)"""
    def sync(self, *, count: int = 25) -> list[SyncResult]: ...

# New protocol wrapper
class SyncTransactionsTool(StandardTool):
    """Tool wrapper exposing sync via Tool protocol."""
    _name = "sync_transactions"
    _description = "Sync transactions from Plaid, categorize, persist"
    _input_schema = {...}  # JSON Schema

    def __init__(self, plaid_client, categorizer, db, taxonomy, access_token):
        self._sync_tool = SyncTool(...)  # Delegate to original

    def _execute_impl(self, **kwargs) -> dict[str, Any]:
        results = self._sync_tool.sync()
        # Return JSON-serializable dict
        return {"status": "success", "total_added": ...}
```

#### 2.2 RecategorizeTool & TagTransactionsTool
**File**: `tools/persist/persist_tool.py`

Wrap `PersistTool.bulk_recategorize_by_merchant()` and `apply_tags()` methods.

#### 2.3 RunSQLTool
**File**: `tools/query/query_tool.py` (NEW)

Wrap `DB.execute_raw_sql()` for natural language SQL queries.

---

### Phase 3: Adapter Layer (Week 3)

#### 3.1 OpenAI Adapter
**File**: `adapters/openai_adapter.py`

```python
class OpenAIAdapter:
    """Convert Tool → @function_tool for Agents SDK."""

    def adapt_tool(self, tool: Tool) -> Callable:
        def wrapper(**kwargs):
            return tool.execute(**kwargs)
        wrapper.__name__ = tool.name
        wrapper.__doc__ = tool.description
        return function_tool(wrapper)

    def adapt_all(self) -> list[Callable]:
        return [self.adapt_tool(t) for t in self._registry.all()]
```

#### 3.2 MCP Adapter
**File**: `adapters/mcp_adapter.py`

Formats tools for **Anthropic MCP SDK**.

```python
class MCPToolDefinition:
    """MCP tool definition for Anthropic MCP SDK."""

    def __init__(self, name: str, description: str, input_schema: dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema


class MCPAdapter:
    """Convert Tool → Anthropic MCP tool definition format."""

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def adapt_tool(self, tool: Tool) -> MCPToolDefinition:
        """Convert Tool to MCP tool definition."""
        return MCPToolDefinition(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )

    def adapt_all(self) -> list[MCPToolDefinition]:
        """Convert all registered tools to MCP format."""
        return [self.adapt_tool(tool) for tool in self._registry.all()]

    def create_handler(self, tool_name: str):
        """Create async handler for MCP server tool registration."""
        tool = self._registry.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found")

        async def handler(arguments: dict) -> dict:
            # MCP handlers are async and receive arguments dict
            return tool.execute(**arguments)

        return handler
```

#### 3.3 ChatKit Adapter
**File**: `adapters/chatkit_adapter.py` (NEW)

```python
class ChatKitAdapter:
    """Convert Tool → ChatKit tool registration format."""

    def adapt_tool(self, tool: Tool) -> dict[str, Any]:
        # ChatKit uses similar format to OpenAI Agents SDK
        # but wrapped in ChatKitServer.respond()
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "handler": lambda **kwargs: tool.execute(**kwargs)
        }
```

#### 3.4 Textual Adapter
**File**: `adapters/textual_adapter.py`

```python
class TextualAdapter:
    """Convert Tool → Textual command structure."""

    def adapt_tool(self, tool: Tool) -> TextualCommand:
        # Extract parameters from JSON Schema
        # Create handler that calls tool.execute()
        return TextualCommand(
            name=tool.name,
            description=tool.description,
            parameters=self._extract_params(tool.input_schema),
            handler=lambda **kwargs: tool.execute(**kwargs)
        )
```

---

### Phase 4: Frontend Implementations (Weeks 4-6)

#### 4.1 Refactor Current Orchestrator (Week 4)
**File**: `orchestrators/transactoid.py`

Update to use Tool Registry + OpenAI Adapter:

```python
class Transactoid:
    def __init__(self, *, db, taxonomy, plaid_client=None):
        self._db = db
        self._taxonomy = taxonomy
        self._registry = ToolRegistry()

    def _register_tools(self, access_token):
        """Register all tools with registry."""
        sync_tool = SyncTransactionsTool(...)
        self._registry.register(sync_tool)
        # ... register other tools

    async def run(self):
        """Run interactive agent with streaming support."""
        self._register_tools(access_token)

        # Adapt tools for OpenAI Agents SDK
        adapter = OpenAIAdapter(self._registry)
        tool_functions = adapter.adapt_all()

        # Create Agent with adapted tools
        agent = Agent(
            name="Transactoid",
            instructions=instructions,
            model="gpt-5.1",
            tools=tool_functions,
            model_settings=ModelSettings(
                reasoning=Reasoning(effort="medium"),
                verbosity="high"
            ),
        )

        # Interactive loop with streaming (unchanged)
        session = TransactoidSession(agent)
        renderer = StreamRenderer()
        await session.run_turn(user_input, renderer, router)
```

**Key Preservation**:
- Streaming support via `StreamRenderer` and `EventRouter` (UNCHANGED)
- `TransactoidSession` for conversation memory (UNCHANGED)
- Interactive loop behavior (UNCHANGED)

#### 4.2 ChatKit Server (Week 5)
**File**: `frontends/chatkit_server.py` (NEW)

```python
from chatkit import ChatKitServer
from adapters.chatkit_adapter import ChatKitAdapter

class TransactoidChatKitServer(ChatKitServer):
    """ChatKit server exposing Transactoid tools."""

    def __init__(self):
        super().__init__()
        # Initialize services
        self._db = DB(os.environ.get("DATABASE_URL"))
        self._taxonomy = Taxonomy.from_db(self._db)

        # Initialize registry and register tools
        self._registry = ToolRegistry()
        self._register_tools()

        # Create ChatKit adapter
        self._adapter = ChatKitAdapter(self._registry)

    def _register_tools(self):
        """Register all tools."""
        # Same registration logic as Transactoid
        sync_tool = SyncTransactionsTool(...)
        self._registry.register(sync_tool)
        # ...

    async def respond(self, ctx):
        """ChatKit respond method - handles each user message."""
        # Use OpenAI Agents SDK with adapted tools
        tools = self._adapter.adapt_all()

        agent = Agent(
            name="Transactoid",
            instructions=instructions,
            tools=tools,
        )

        # Use stream_agent_response helper for streaming
        await stream_agent_response(
            agent=agent,
            messages=ctx.messages,
            ctx=ctx,
        )

# Entry point
if __name__ == "__main__":
    server = TransactoidChatKitServer()
    server.run(host="0.0.0.0", port=8000)
```

**ChatKit Integration Notes**:
- Uses `ChatKitServer` base class from `chatkit` Python SDK
- `respond()` method executes for each user message
- `stream_agent_response()` helper connects to Agents SDK
- Streaming automatically handled by ChatKit
- Frontend uses ChatKit.js (React component)

#### 4.3 MCP Server (Week 5)
**File**: `frontends/mcp_server.py` (NEW)

Uses **Anthropic MCP Python SDK** for implementation.

```python
from mcp.server import Server  # Anthropic MCP SDK
from mcp.server.stdio import stdio_server
from adapters.mcp_adapter import MCPAdapter

class TransactoidMCPServer:
    """MCP server exposing Transactoid tools via Anthropic MCP SDK."""

    def __init__(self):
        # Initialize services and registry
        self._db = DB(os.environ.get("DATABASE_URL"))
        self._taxonomy = Taxonomy.from_db(self._db)
        self._registry = ToolRegistry()
        self._register_tools()
        self._adapter = MCPAdapter(self._registry)

        # Create MCP server instance
        self._server = Server("transactoid")

    def _register_tools(self):
        """Register tools (same as other frontends)."""
        # Same registration as ChatKit/CLI
        plaid_client = PlaidClient.from_env()
        access_token = self._get_access_token()

        sync_tool = SyncTransactionsTool(...)
        self._registry.register(sync_tool)
        # ... register other tools

    async def run(self):
        """Run MCP server using stdio transport."""
        # Register tool handlers with MCP server
        for tool_def in self._adapter.adapt_all():
            @self._server.tool(tool_def.name)
            async def tool_handler(arguments: dict) -> str:
                result = self._registry.execute(tool_def.name, **arguments)
                return json.dumps(result)

        # Start stdio server
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options()
            )

# Entry point
if __name__ == "__main__":
    server = TransactoidMCPServer()
    asyncio.run(server.run())
```

**Installation**:
```bash
uv add mcp  # Anthropic MCP SDK
```

**Usage**:
```bash
# Run MCP server
python -m frontends.mcp_server

# Or add to MCP client config (e.g., Claude Desktop)
# ~/.config/claude/mcp.json:
{
  "transactoid": {
    "command": "python",
    "args": ["-m", "frontends.mcp_server"]
  }
}
```

#### 4.4 Web & Mobile Frontends (Future - Week 6+)

Both web and mobile apps are **chat-focused UIs** that connect to the ChatKit server as clients.

**Web App (React/Next.js) with ChatKit.js**:
```bash
# Create Next.js app
cd web
npm install @openai/chatkit-js

# src/app/page.tsx
import { ChatKit } from '@openai/chatkit-js';

export default function Home() {
  return (
    <main>
      <h1>Transactoid - Personal Finance Agent</h1>
      <ChatKit
        serverUrl="http://localhost:8000"  // ChatKit server
        theme="dark"
        placeholder="Ask about your finances..."
      />
    </main>
  );
}
```

**Mobile App (React Native) with ChatKit**:
```bash
# Create React Native app
cd mobile
npm install @openai/chatkit-react-native

# Or use WebView approach:
import { WebView } from 'react-native-webview';

export default function App() {
  return (
    <WebView
      source={{ uri: 'http://localhost:8000' }}  // ChatKit web interface
      style={{ flex: 1 }}
    />
  );
}
```

**Benefits of ChatKit-based approach**:
- **Simpler**: No need for separate REST API
- **Consistent UX**: Same chat interface across CLI, web, and mobile
- **Agent-powered**: Full conversational capabilities
- **Streaming**: Real-time responses
- **Maintained**: ChatKit handles updates and improvements

#### 4.5 Headless Mode (Future - Week 6+)
**File**: `frontends/headless.py` (NEW)

Run agent programmatically for evals/testing without UI.

```python
class HeadlessTransactoid:
    """
    Headless mode for running Transactoid programmatically.

    Use cases:
    - Automated testing/evals
    - Batch processing
    - Integration tests
    - CI/CD pipelines
    """

    def __init__(self, db_url: str | None = None):
        self._db = DB(db_url or os.environ.get("DATABASE_URL"))
        self._taxonomy = Taxonomy.from_db(self._db)
        self._registry = ToolRegistry()
        self._register_tools()

    def _register_tools(self):
        """Same tool registration."""
        # ...

    async def execute_tool(self, tool_name: str, **kwargs) -> dict:
        """Execute a tool directly."""
        return self._registry.execute(tool_name, **kwargs)

    async def run_agent_turn(
        self,
        message: str,
        conversation_history: list[dict] | None = None
    ) -> dict:
        """
        Run a single agent turn without streaming.

        Returns:
            {
                "response": "Agent's text response",
                "tool_calls": [{tool_name, arguments, result}, ...],
                "conversation_history": [updated history]
            }
        """
        # Create agent with tools
        adapter = OpenAIAdapter(self._registry)
        tools = adapter.adapt_all()

        agent = Agent(
            name="Transactoid",
            instructions=self._get_instructions(),
            model="gpt-5.1",
            tools=tools,
        )

        # Run turn without streaming
        session = TransactoidSession(agent)
        # Capture output without printing
        result = await session.run_turn_silent(message)

        return {
            "response": result.response_text,
            "tool_calls": result.tool_calls,
            "conversation_history": result.messages,
        }

    async def run_eval_scenario(self, scenario: dict) -> dict:
        """
        Run an eval scenario.

        scenario: {
            "name": "Test sync and query",
            "steps": [
                {"type": "tool", "tool": "sync_transactions", "args": {}},
                {"type": "agent", "message": "How much did I spend on food?"},
            ]
        }
        """
        results = []
        for step in scenario["steps"]:
            if step["type"] == "tool":
                result = await self.execute_tool(step["tool"], **step.get("args", {}))
                results.append({"step": step, "result": result})
            elif step["type"] == "agent":
                result = await self.run_agent_turn(step["message"])
                results.append({"step": step, "result": result})

        return {
            "scenario": scenario["name"],
            "results": results,
            "success": all(r["result"].get("status") != "error" for r in results)
        }
```

**Usage in Tests**:
```python
@pytest.mark.asyncio
async def test_sync_and_query_workflow():
    """Integration test using headless mode."""
    headless = HeadlessTransactoid(db_url="sqlite:///:memory:")

    # Step 1: Sync transactions
    sync_result = await headless.execute_tool("sync_transactions")
    assert sync_result["status"] == "success"

    # Step 2: Query via agent
    query_result = await headless.run_agent_turn(
        "How much did I spend on groceries this month?"
    )
    assert "groceries" in query_result["response"].lower()

    # Step 3: Verify tool was called
    assert any(tc["tool_name"] == "run_sql" for tc in query_result["tool_calls"])
```

**Usage for Evals**:
```python
async def run_evals():
    """Run evaluation suite."""
    headless = HeadlessTransactoid()

    scenarios = [
        {
            "name": "Sync and categorize",
            "steps": [
                {"type": "tool", "tool": "sync_transactions", "args": {}},
                {"type": "agent", "message": "Show me my top 5 spending categories"},
            ]
        },
        # ... more scenarios
    ]

    results = []
    for scenario in scenarios:
        result = await headless.run_eval_scenario(scenario)
        results.append(result)

    # Report results
    success_rate = sum(r["success"] for r in results) / len(results)
    print(f"Eval success rate: {success_rate:.1%}")
```

#### 4.6 Hex Integration (No Code Required)
**Hex** (hex.tech) is a data analytics platform that can connect directly to databases.

**Setup**:
1. In Hex, create a new data connection
2. Select PostgreSQL (or SQLite if using local)
3. Use `DATABASE_URL` from environment:
   - Host, port, database, user, password
4. Test connection

**Access**:
Hex directly queries the database using the ORM schema:
- `transactions` table - All transaction data
- `merchants` table - Normalized merchant names
- `categories` table - Taxonomy categories
- `tags` table - User-defined tags
- `plaid_items` table - Connected Plaid accounts

**Example Hex SQL Cell**:
```sql
-- Top spending categories this month
SELECT
    c.parent_name,
    c.child_name,
    SUM(t.amount) as total_spent,
    COUNT(*) as transaction_count
FROM transactions t
JOIN categories c ON t.category_id = c.id
WHERE t.date >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY c.parent_name, c.child_name
ORDER BY total_spent DESC
LIMIT 10;
```

**Benefits**:
- No API or tool integration needed
- Direct SQL access to all data
- Hex's visualization and reporting features
- Can use Hex's Python cells to call Transactoid tools if needed:
  ```python
  # In Hex Python cell (advanced)
  from frontends.headless import HeadlessTransactoid

  headless = HeadlessTransactoid()
  result = await headless.execute_tool("sync_transactions")
  ```

**Note**: Hex integration requires no changes to Transactoid architecture - it uses the existing DB service directly.

#### 4.7 Textual UI (Future - Week 6+)
**File**: `frontends/textual_ui.py` (NEW)

Lower priority - placeholder implementation.

```python
from textual.app import App
from textual.widgets import Input, DataTable, Header, Footer
from adapters.textual_adapter import TextualAdapter

class TransactoidTUI(App):
    """Textual TUI for Transactoid."""

    def __init__(self):
        super().__init__()
        # Initialize services and registry
        self._db = DB(os.environ.get("DATABASE_URL"))
        self._taxonomy = Taxonomy.from_db(self._db)
        self._registry = ToolRegistry()
        self._register_tools()

        # Create Textual adapter
        self._adapter = TextualAdapter(self._registry)
        self._commands = {
            cmd.name: cmd for cmd in self._adapter.adapt_all()
        }

    def compose(self):
        """Create UI layout."""
        yield Header()
        yield Input(placeholder="Enter SQL or /command", id="input")
        yield DataTable(id="results")
        yield Footer()

    def on_input_submitted(self, event):
        """Handle user input."""
        query = event.value

        if query.startswith("/"):
            # Tool command (e.g., /sync_transactions)
            tool_name = query[1:].split()[0]
            result = self._registry.execute(tool_name)
            self.display_result(result)
        else:
            # SQL query
            result = self._registry.execute("run_sql", query=query)
            self.display_table(result.get("rows", []))

# Entry point
def main():
    app = TransactoidTUI()
    app.run()
```

---

## Directory Structure

```
transactoid/
├── adapters/                      # NEW: Frontend adapters
│   ├── __init__.py
│   ├── openai_adapter.py         # OpenAI Agents SDK (CLI + Headless)
│   ├── chatkit_adapter.py        # ChatKit integration
│   ├── mcp_adapter.py            # MCP server (Anthropic SDK)
│   └── textual_adapter.py        # Textual UI (future)
├── frontends/                     # NEW: Frontend implementations
│   ├── __init__.py
│   ├── chatkit_server.py         # ChatKit server (high priority)
│   ├── mcp_server.py             # MCP server (high priority)
│   ├── headless.py               # Headless mode for evals (future)
│   └── textual_ui.py             # Textual TUI (future)
├── tools/
│   ├── __init__.py
│   ├── protocol.py               # NEW: Tool protocol interface
│   ├── base.py                   # NEW: StandardTool base class
│   ├── registry.py               # NEW: ToolRegistry
│   ├── sync/
│   │   ├── __init__.py
│   │   └── sync_tool.py          # ADD: SyncTransactionsTool wrapper
│   ├── persist/
│   │   ├── __init__.py
│   │   └── persist_tool.py       # ADD: Recategorize/Tag wrappers
│   ├── categorize/
│   │   ├── __init__.py
│   │   └── categorizer_tool.py   # UNCHANGED (optional wrapper)
│   └── query/                     # NEW: SQL query tool
│       ├── __init__.py
│       └── query_tool.py         # NEW: RunSQLTool
├── orchestrators/
│   ├── __init__.py
│   └── transactoid.py            # REFACTOR: Use adapters
├── services/                      # UNCHANGED
│   ├── __init__.py
│   ├── db.py
│   ├── taxonomy.py
│   ├── file_cache.py
│   └── plaid_client.py
├── ui/
│   ├── __init__.py
│   └── cli.py                    # UNCHANGED: Entry point
├── web/                           # FUTURE: Web app frontend
│   ├── package.json
│   ├── src/
│   │   ├── api/                  # REST API client
│   │   ├── components/           # React components
│   │   └── pages/                # Next.js pages
│   └── ...
├── mobile/                        # FUTURE: Mobile app
│   ├── package.json
│   ├── src/
│   │   ├── api/                  # REST API client
│   │   ├── screens/              # React Native screens
│   │   └── components/           # Shared components
│   └── ...
└── tests/
    ├── adapters/                 # NEW: Adapter tests
    ├── tools/
    │   ├── test_protocol.py      # NEW: Protocol tests
    │   └── test_wrappers.py      # NEW: Wrapper tests
    ├── integration/              # NEW: End-to-end tests
    │   └── test_headless.py      # NEW: Headless mode tests
    └── ...
```

---

## Critical Implementation Details

### Streaming Support Preservation

**Current Streaming Architecture**:
```python
# orchestrators/transactoid.py
renderer = StreamRenderer()
router = EventRouter(renderer)
await session.run_turn(user_input, renderer, router)
```

**Preservation Strategy**:
- OpenAI Adapter: Maintains existing streaming via `StreamRenderer` and `EventRouter`
- ChatKit Adapter: Uses `stream_agent_response()` helper (built-in streaming)
- MCP: Request/response (no streaming initially, can be added)
- Textual: Request/response for simple queries, streaming for agent interactions

### Tool Registration Pattern

**Consistent across all frontends**:
```python
def _register_tools(self):
    """Same logic used by CLI, ChatKit, MCP, and Textual."""
    # Get dependencies
    plaid_client = PlaidClient.from_env()
    access_token = self._get_access_token()

    # Register tools
    sync_tool = SyncTransactionsTool(
        plaid_client=plaid_client,
        categorizer=self._categorizer,
        db=self._db,
        taxonomy=self._taxonomy,
        access_token=access_token,
    )
    self._registry.register(sync_tool)

    recat_tool = RecategorizeTool(self._persist_tool)
    self._registry.register(recat_tool)

    tag_tool = TagTransactionsTool(self._persist_tool)
    self._registry.register(tag_tool)

    sql_tool = RunSQLTool(self._db)
    self._registry.register(sql_tool)
```

### Error Handling

**Standardized error format**:
```python
# All tools return dicts with consistent error format
def _execute_impl(self, **kwargs) -> dict[str, Any]:
    try:
        result = self._do_work(**kwargs)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

---

## Testing Strategy

### Unit Tests

**Phase 1: Protocol Tests** (`tests/tools/test_protocol.py`)
- Test Tool protocol compliance
- Test StandardTool base class
- Test ToolRegistry registration and lookup

**Phase 2: Wrapper Tests** (`tests/tools/test_wrappers.py`)
- Test each tool wrapper independently
- Mock underlying tool implementations
- Verify JSON-serializable outputs

**Phase 3: Adapter Tests** (`tests/adapters/`)
- Test OpenAI adapter converts tools correctly
- Test ChatKit adapter format
- Test MCP adapter tool definitions
- Test Textual adapter command generation

### Integration Tests

**Phase 4: End-to-End Tests** (`tests/integration/`)
- Test orchestrator with adapted tools
- Test ChatKit server with mock requests
- Test MCP server tool invocation
- Test Textual UI command execution

---

## Migration & Rollout Strategy

### Implementation Order

**High Priority (Weeks 1-5)**:
- **Week 1**: Foundation (Protocol, Base, Registry)
- **Week 2**: Tool Wrappers (Sync, Persist, Query)
- **Week 3**: Adapters (OpenAI, ChatKit, MCP) - Textual adapter deferred
- **Week 4**: Current CLI Refactoring
- **Week 5**: ChatKit + MCP Servers (parallel implementation)

**Lower Priority (Future)**:
- **Week 6+**: Textual UI (when needed)
  - Textual adapter implementation
  - Basic UI scaffold with SQL query focus
  - Can be expanded based on requirements

### Validation at Each Phase

1. Run existing test suite (must pass)
2. Run `mypy --config-file mypy.ini .` (strict mode)
3. Run `uv run ruff check .`
4. Run `uv run ruff format --check .`
5. Manual testing of existing CLI

### Backward Compatibility Guarantee

- Original tool classes (SyncTool, Categorizer, PersistTool) UNCHANGED
- All services (DB, Taxonomy, FileCache, PlaidClient) UNCHANGED
- Existing CLI command `transactoid` continues working
- Streaming behavior preserved
- No breaking changes to existing APIs

---

## Entry Points

After implementation, users will have multiple ways to run and interact with Transactoid:

### High Priority (Weeks 1-5)

```bash
# Current CLI (interactive agent with streaming)
transactoid

# ChatKit server (embeddable chat interface for web)
python -m frontends.chatkit_server
# Runs on: http://localhost:8000

# MCP server (expose tools via Anthropic MCP protocol)
python -m frontends.mcp_server
# Or add to Claude Desktop config

# Agent configuration in Claude Desktop (~/.config/claude/mcp.json):
{
  "transactoid": {
    "command": "python",
    "args": ["-m", "frontends.mcp_server"],
    "env": {
      "DATABASE_URL": "postgresql://...",
      "PLAID_CLIENT_ID": "...",
      "PLAID_SANDBOX_SECRET": "..."
    }
  }
}
```

### Future Frontends (Week 6+)

```bash
# Headless mode (for evals/testing) - Python API
from frontends.headless import HeadlessTransactoid
headless = HeadlessTransactoid()
result = await headless.execute_tool("sync_transactions")

# Textual UI (terminal interface)
python -m frontends.textual_ui

# Web app (React/Next.js) - ChatKit client
cd web
npm run dev
# App at: http://localhost:3000
# Connects to ChatKit server at http://localhost:8000

# Mobile app (React Native) - ChatKit client or WebView
cd mobile
npm start
# Connects to ChatKit server
```

### Hex Integration (No code - direct DB access)

```
1. Add Transactoid DB as data connection in Hex
2. Use DATABASE_URL credentials
3. Query directly with SQL or use Python cells
```

---

## Design Decisions

### 1. Protocol vs ABC
**Choice**: Use `typing.Protocol` instead of `abc.ABC`
**Rationale**: Structural typing allows existing classes to be adapted without inheritance

### 2. Wrapper Pattern
**Choice**: Create wrapper classes instead of modifying existing tools
**Rationale**: Zero risk to business logic, easier rollback, clear separation

### 3. No DI Framework
**Choice**: Simple ToolRegistry instead of dependency injection framework
**Rationale**: Minimizes dependencies, easier to understand, sufficient for needs

### 4. Separate Adapters
**Choice**: One adapter per frontend instead of generic adapter
**Rationale**: Each frontend has unique requirements, easier to optimize and test

---

## Success Criteria

### Functional
- ✅ Current CLI works unchanged with streaming
- ✅ ChatKit server exposes tools via embeddable interface
- ✅ MCP server lists and executes tools
- ✅ Textual UI provides interactive terminal interface
- ✅ All tools execute correctly through adapters
- ✅ mypy strict mode passes
- ✅ All tests pass (existing + new)

### Non-Functional
- ✅ No performance regression
- ✅ Clear separation of concerns
- ✅ Easy to add new frontends
- ✅ Comprehensive documentation
- ✅ Backward compatibility maintained

---

## Critical Files to Implement

### Phase 1: Foundation (Week 1) - CRITICAL

1. `/Users/adambossy/code/transactoid/tools/protocol.py` - Tool interface definition
2. `/Users/adambossy/code/transactoid/tools/base.py` - StandardTool base class
3. `/Users/adambossy/code/transactoid/tools/registry.py` - ToolRegistry implementation

### Phase 2: Tool Wrappers (Week 2) - CRITICAL

4. `/Users/adambossy/code/transactoid/tools/sync/sync_tool.py` - Add SyncTransactionsTool wrapper
5. `/Users/adambossy/code/transactoid/tools/persist/persist_tool.py` - Add Recategorize/Tag wrappers
6. `/Users/adambossy/code/transactoid/tools/query/query_tool.py` - NEW: RunSQLTool

### Phase 3: Adapters (Week 3) - CRITICAL

7. `/Users/adambossy/code/transactoid/adapters/openai_adapter.py` - OpenAI Agents SDK integration
8. `/Users/adambossy/code/transactoid/adapters/chatkit_adapter.py` - ChatKit integration
9. `/Users/adambossy/code/transactoid/adapters/mcp_adapter.py` - MCP integration (Anthropic SDK)

### Phase 4-5: High Priority Frontends (Weeks 4-5) - CRITICAL

10. `/Users/adambossy/code/transactoid/orchestrators/transactoid.py` - Refactor to use adapters
11. `/Users/adambossy/code/transactoid/frontends/chatkit_server.py` - ChatKit server implementation
12. `/Users/adambossy/code/transactoid/frontends/mcp_server.py` - MCP server implementation

### Future Frontends (Week 6+) - OPTIONAL

13. `/Users/adambossy/code/transactoid/adapters/textual_adapter.py` - Textual UI adapter
14. `/Users/adambossy/code/transactoid/frontends/headless.py` - Headless mode for evals
15. `/Users/adambossy/code/transactoid/frontends/textual_ui.py` - Textual UI implementation
16. `web/` - Web app using ChatKit.js
17. `mobile/` - Mobile app using ChatKit or WebView

---

## Design Decisions (Answered)

1. **ChatKit Hosting**: ✅ Self-hosted using ChatKit Python SDK + FastAPI
   - Run on own infrastructure with full control
   - More flexible than OpenAI Agent Builder

2. **MCP Protocol**: ✅ Anthropic MCP SDK
   - Use official Anthropic MCP Python SDK
   - Most mature and well-documented implementation

3. **Authentication**: ✅ Environment variables only
   - All frontends read DATABASE_URL, PLAID credentials from environment
   - Simple and consistent with current CLI approach
   - Suitable for local/development use

4. **Textual UI**: ✅ Placeholder/lower priority
   - Architecture designed to support it, but implementation deferred
   - ChatKit and MCP frontends are higher priority
   - Can be fully implemented later when needed

5. **Deployment**: ✅ Docker containers deferred
   - Focus on getting code working first
   - Direct Python execution (`python -m frontends.chatkit_server`)
   - Dockerfiles can be added later if needed

---

## Sources

- [Introducing AgentKit | OpenAI](https://openai.com/index/introducing-agentkit/)
- [Advanced integrations with ChatKit | OpenAI API](https://platform.openai.com/docs/guides/custom-chatkit)
- [ChatKit | OpenAI API](https://platform.openai.com/docs/guides/chatkit)
- [Chatkit Python SDK](https://openai.github.io/chatkit-python/)
- [Server Integration - Chatkit Python SDK](https://openai.github.io/chatkit-python/server/)
