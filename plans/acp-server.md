# ACP Server Implementation Plan

> **Status**: PLANNING
> **Prerequisite**: Delete core Transactoid agent (gt-1xx)

## Executive Summary

Implement an Agent Client Protocol (ACP) compliant server to integrate Transactoid with ACP-compatible code editors (VS Code extensions, Cursor, etc.).

**Key Finding**: Neither the existing ChatKit server nor MCP server is ACP-compliant. They serve different purposes:

| Protocol | Purpose | Communication | Use Case |
|----------|---------|---------------|----------|
| **ACP** | Editor ↔ Agent integration | Bidirectional JSON-RPC via stdin/stdout | VS Code, Cursor, etc. |
| **MCP** | Tool exposure to LLM clients | Unidirectional (client → server) | Claude Desktop, etc. |
| **ChatKit** | OpenAI-specific UI | HTTP/SSE | OpenAI ChatKit UI |

**ACP is "MCP-friendly"** (reuses MCP types) but MCP servers don't automatically conform to ACP.

---

## ACP Protocol Requirements

### Initialization (`initialize`)

**Client sends:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {
      "readTextFile": true,
      "writeTextFile": true,
      "terminal": true
    },
    "clientInfo": {
      "name": "cursor",
      "version": "1.0.0"
    }
  }
}
```

**Agent responds:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": 1,
    "agentCapabilities": {
      "promptTypes": {
        "image": false,
        "audio": false,
        "embeddedContext": true
      },
      "mcp": {
        "http": false,
        "sse": false
      }
    },
    "agentInfo": {
      "name": "transactoid",
      "title": "Transactoid Finance Agent",
      "version": "0.1.0"
    },
    "authMethods": []
  }
}
```

### Session Management

#### Create Session (`session/new`)
```json
{
  "method": "session/new",
  "params": {
    "cwd": "/home/user/project",
    "mcpServers": []
  }
}
```

Response includes unique `sessionId`.

#### Process Prompt (`session/prompt`)
```json
{
  "method": "session/prompt",
  "params": {
    "sessionId": "sess_abc123",
    "content": [
      {"type": "text", "text": "How much did I spend on groceries?"}
    ]
  }
}
```

### Real-time Updates (`session/update` notifications)

**Tool call start:**
```json
{
  "method": "session/update",
  "params": {
    "update": {
      "sessionUpdate": "tool_call",
      "toolCallId": "call_001",
      "title": "Querying database",
      "kind": "execute",
      "status": "pending"
    }
  }
}
```

**Tool call progress:**
```json
{
  "method": "session/update",
  "params": {
    "update": {
      "sessionUpdate": "tool_call_update",
      "toolCallId": "call_001",
      "status": "in_progress"
    }
  }
}
```

**Tool call complete:**
```json
{
  "method": "session/update",
  "params": {
    "update": {
      "sessionUpdate": "tool_call_update",
      "toolCallId": "call_001",
      "status": "completed",
      "content": [{"type": "text", "text": "Query returned 15 rows"}]
    }
  }
}
```

**Message streaming:**
```json
{
  "method": "session/update",
  "params": {
    "update": {
      "sessionUpdate": "message_delta",
      "content": [{"type": "text", "text": "Based on your transactions..."}]
    }
  }
}
```

### Permission Requests (`session/request_permission`)

Agent calls client when needing authorization:
```json
{
  "method": "session/request_permission",
  "params": {
    "sessionId": "sess_abc123",
    "title": "Execute SQL Query",
    "message": "Agent wants to run: SELECT * FROM transactions",
    "options": [
      {"optionId": "allow_once", "label": "Allow once"},
      {"optionId": "allow_always", "label": "Always allow SQL"},
      {"optionId": "reject_once", "label": "Reject"}
    ]
  }
}
```

### Client Callbacks (Agent → Client)

**File read:**
```json
{
  "method": "fs/read_text_file",
  "params": {
    "sessionId": "sess_abc123",
    "path": "/home/user/project/config.json"
  }
}
```

**File write:**
```json
{
  "method": "fs/write_text_file",
  "params": {
    "sessionId": "sess_abc123",
    "path": "/home/user/project/output.json",
    "content": "{\"result\": \"success\"}"
  }
}
```

**Terminal commands:**
```json
{
  "method": "terminal/create",
  "params": {
    "sessionId": "sess_abc123",
    "command": "ls",
    "args": ["-la"],
    "cwd": "/home/user/project"
  }
}
```

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      ACP Server Process                          │
│                                                                  │
│  ┌────────────────┐     ┌─────────────────┐                     │
│  │  JSON-RPC      │────▶│  Request        │                     │
│  │  Transport     │     │  Router         │                     │
│  │  (stdin/stdout)│◀────│                 │                     │
│  └────────────────┘     └────────┬────────┘                     │
│                                  │                               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Protocol Handlers                         │ │
│  │                                                              │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │ │
│  │  │ Initialize   │  │ Session      │  │ Update       │       │ │
│  │  │ Handler      │  │ Handler      │  │ Notifier     │       │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                  │                               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    ACP Adapter                               │ │
│  │  - Wraps ToolRegistry                                       │ │
│  │  - Converts Tool calls to ACP updates                       │ │
│  │  - Manages session state                                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                  │                               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Tool Registry                             │ │
│  │  (Existing - shared with ChatKit/MCP)                       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                  │                               │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Services (DB, Taxonomy, etc.)             │ │
│  │  (Existing - unchanged)                                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
transactoid/
├── ui/
│   ├── acp/                          # NEW: ACP server
│   │   ├── __init__.py
│   │   ├── server.py                 # Main entry point
│   │   ├── transport.py              # JSON-RPC stdin/stdout transport
│   │   ├── router.py                 # Request routing
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── initialize.py         # Initialize handler
│   │   │   ├── session.py            # Session management
│   │   │   └── prompt.py             # Prompt processing
│   │   ├── notifier.py               # session/update notifications
│   │   └── types.py                  # ACP-specific types
│   ├── chatkit/                      # Existing
│   ├── mcp/                          # Existing
│   └── ...
├── adapters/
│   ├── acp_adapter.py                # NEW: ACP adapter
│   └── ...
└── ...
```

---

## Implementation Plan

### Phase 1: Transport Layer

**File**: `ui/acp/transport.py`

```python
"""JSON-RPC transport over stdin/stdout."""

import json
import sys
from typing import Any
from dataclasses import dataclass

@dataclass
class JsonRpcMessage:
    """Base JSON-RPC message."""
    jsonrpc: str = "2.0"

@dataclass
class JsonRpcRequest(JsonRpcMessage):
    """JSON-RPC request."""
    id: int | str | None
    method: str
    params: dict[str, Any] | None = None

@dataclass
class JsonRpcResponse(JsonRpcMessage):
    """JSON-RPC response."""
    id: int | str | None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

@dataclass
class JsonRpcNotification(JsonRpcMessage):
    """JSON-RPC notification (no id)."""
    method: str
    params: dict[str, Any] | None = None

class StdioTransport:
    """Bidirectional JSON-RPC transport via stdin/stdout."""

    async def read_message(self) -> JsonRpcRequest:
        """Read next JSON-RPC request from stdin."""
        line = await asyncio.get_event_loop().run_in_executor(
            None, sys.stdin.readline
        )
        data = json.loads(line)
        return JsonRpcRequest(**data)

    async def write_response(self, response: JsonRpcResponse) -> None:
        """Write JSON-RPC response to stdout."""
        sys.stdout.write(json.dumps(asdict(response)) + "\n")
        sys.stdout.flush()

    async def write_notification(self, notification: JsonRpcNotification) -> None:
        """Write JSON-RPC notification to stdout."""
        sys.stdout.write(json.dumps(asdict(notification)) + "\n")
        sys.stdout.flush()
```

### Phase 2: Request Router

**File**: `ui/acp/router.py`

```python
"""Route JSON-RPC requests to handlers."""

from typing import Callable, Awaitable, Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

class RequestRouter:
    """Route JSON-RPC methods to handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        """Register handler for method."""
        self._handlers[method] = handler

    async def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch request to handler."""
        handler = self._handlers.get(method)
        if handler is None:
            raise ValueError(f"Unknown method: {method}")
        return await handler(params)
```

### Phase 3: Protocol Handlers

**File**: `ui/acp/handlers/initialize.py`

```python
"""Initialize handler for ACP."""

from typing import Any

async def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    """Handle initialize request."""
    client_version = params.get("protocolVersion", 1)

    return {
        "protocolVersion": min(client_version, 1),  # Support v1
        "agentCapabilities": {
            "promptTypes": {
                "image": False,
                "audio": False,
                "embeddedContext": True,
            },
            "mcp": {
                "http": False,
                "sse": False,
            },
        },
        "agentInfo": {
            "name": "transactoid",
            "title": "Transactoid Finance Agent",
            "version": "0.1.0",
        },
        "authMethods": [],
    }
```

**File**: `ui/acp/handlers/session.py`

```python
"""Session management handlers."""

import uuid
from typing import Any
from dataclasses import dataclass, field

@dataclass
class Session:
    """ACP session state."""
    id: str
    cwd: str
    mcp_servers: list[dict[str, Any]]
    messages: list[dict[str, Any]] = field(default_factory=list)

class SessionManager:
    """Manage ACP sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, cwd: str, mcp_servers: list[dict[str, Any]]) -> str:
        """Create new session, return session ID."""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = Session(
            id=session_id,
            cwd=cwd,
            mcp_servers=mcp_servers,
        )
        return session_id

    def get(self, session_id: str) -> Session | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Add message to session history."""
        session = self._sessions.get(session_id)
        if session:
            session.messages.append(message)
```

**File**: `ui/acp/handlers/prompt.py`

```python
"""Prompt processing handler."""

import uuid
from typing import Any, AsyncIterator

from agents import Agent, ModelSettings, Runner
from openai.types.shared import Reasoning

class PromptHandler:
    """Handle session/prompt requests."""

    def __init__(
        self,
        session_manager: SessionManager,
        tool_registry: ToolRegistry,
        notifier: UpdateNotifier,
    ) -> None:
        self._sessions = session_manager
        self._registry = tool_registry
        self._notifier = notifier

    async def handle_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Process user prompt and stream responses."""
        session_id = params["sessionId"]
        content = params["content"]

        session = self._sessions.get(session_id)
        if session is None:
            return {"error": {"code": -32600, "message": "Invalid session"}}

        # Extract text from content blocks
        user_text = ""
        for block in content:
            if block.get("type") == "text":
                user_text = block["text"]
                break

        # Create agent with tools
        adapter = OpenAIAdapter(self._registry)
        tools = adapter.adapt_all()

        agent = Agent(
            name="Transactoid",
            instructions=self._get_instructions(),
            model="gpt-5.1",
            tools=tools,
            model_settings=ModelSettings(
                reasoning=Reasoning(effort="medium"),
                verbosity="high",
            ),
        )

        # Run with streaming, sending updates via notifier
        result = Runner.run_streamed(
            starting_agent=agent,
            input=user_text,
        )

        # Stream events as session/update notifications
        async for event in result.stream_events():
            await self._process_event(session_id, event)

        return {"stopReason": "end_turn"}

    async def _process_event(self, session_id: str, event: Any) -> None:
        """Convert agent event to ACP update notification."""
        if event.type == "tool_call_start":
            await self._notifier.tool_call(
                session_id=session_id,
                tool_call_id=event.tool_call_id,
                title=event.tool_name,
                kind="execute",
                status="pending",
            )
        elif event.type == "tool_call_complete":
            await self._notifier.tool_call_update(
                session_id=session_id,
                tool_call_id=event.tool_call_id,
                status="completed",
                content=[{"type": "text", "text": str(event.result)}],
            )
        elif event.type == "text_delta":
            await self._notifier.message_delta(
                session_id=session_id,
                content=[{"type": "text", "text": event.text}],
            )
```

### Phase 4: Update Notifier

**File**: `ui/acp/notifier.py`

```python
"""ACP session/update notification sender."""

from typing import Any
from .transport import StdioTransport, JsonRpcNotification

class UpdateNotifier:
    """Send session/update notifications."""

    def __init__(self, transport: StdioTransport) -> None:
        self._transport = transport

    async def tool_call(
        self,
        session_id: str,
        tool_call_id: str,
        title: str,
        kind: str,
        status: str,
    ) -> None:
        """Send tool_call update."""
        await self._send_update({
            "sessionUpdate": "tool_call",
            "toolCallId": tool_call_id,
            "title": title,
            "kind": kind,
            "status": status,
        })

    async def tool_call_update(
        self,
        session_id: str,
        tool_call_id: str,
        status: str,
        content: list[dict[str, Any]] | None = None,
    ) -> None:
        """Send tool_call_update."""
        update: dict[str, Any] = {
            "sessionUpdate": "tool_call_update",
            "toolCallId": tool_call_id,
            "status": status,
        }
        if content:
            update["content"] = content
        await self._send_update(update)

    async def message_delta(
        self,
        session_id: str,
        content: list[dict[str, Any]],
    ) -> None:
        """Send message_delta update."""
        await self._send_update({
            "sessionUpdate": "message_delta",
            "content": content,
        })

    async def _send_update(self, update: dict[str, Any]) -> None:
        """Send session/update notification."""
        notification = JsonRpcNotification(
            method="session/update",
            params={"update": update},
        )
        await self._transport.write_notification(notification)
```

### Phase 5: Main Server

**File**: `ui/acp/server.py`

```python
"""ACP server main entry point."""

import asyncio
import os
from dotenv import load_dotenv

from transactoid.adapters.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.persist.persist_tool import PersistTool
from transactoid.tools.registry import ToolRegistry

from .transport import StdioTransport
from .router import RequestRouter
from .handlers.initialize import handle_initialize
from .handlers.session import SessionManager
from .handlers.prompt import PromptHandler
from .notifier import UpdateNotifier

class ACPServer:
    """Agent Client Protocol server."""

    def __init__(self) -> None:
        # Initialize services
        db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        self._db = DB(db_url)
        self._taxonomy = load_taxonomy_from_db(self._db)
        self._categorizer = Categorizer(self._taxonomy)
        self._persist_tool = PersistTool(self._db, self._taxonomy)

        # Initialize registry and register tools
        self._registry = ToolRegistry()
        self._register_tools()

        # Initialize transport and router
        self._transport = StdioTransport()
        self._router = RequestRouter()
        self._notifier = UpdateNotifier(self._transport)
        self._sessions = SessionManager()

        # Register handlers
        self._setup_handlers()

    def _register_tools(self) -> None:
        """Register all tools with registry."""
        # Same registration as ChatKit/MCP servers
        from transactoid.adapters.clients.plaid import PlaidClient
        from transactoid.tools.sync.sync_tool import SyncTransactionsTool
        from transactoid.tools.persist.persist_tool import (
            RecategorizeTool,
            TagTransactionsTool,
        )
        from transactoid.tools.query.query_tool import RunSQLTool

        plaid_client = PlaidClient.from_env()
        plaid_items = self._db.list_plaid_items()

        if plaid_items:
            access_token = plaid_items[0].access_token
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

    def _setup_handlers(self) -> None:
        """Register protocol handlers."""
        self._router.register("initialize", handle_initialize)

        # Session handlers
        async def handle_session_new(params: dict) -> dict:
            session_id = self._sessions.create(
                cwd=params["cwd"],
                mcp_servers=params.get("mcpServers", []),
            )
            return {"sessionId": session_id}

        self._router.register("session/new", handle_session_new)

        # Prompt handler
        prompt_handler = PromptHandler(
            session_manager=self._sessions,
            tool_registry=self._registry,
            notifier=self._notifier,
        )
        self._router.register("session/prompt", prompt_handler.handle_prompt)

    async def run(self) -> None:
        """Run the ACP server."""
        while True:
            try:
                request = await self._transport.read_message()
                result = await self._router.dispatch(
                    request.method,
                    request.params or {},
                )
                response = JsonRpcResponse(
                    id=request.id,
                    result=result,
                )
                await self._transport.write_response(response)
            except Exception as e:
                if request.id is not None:
                    error_response = JsonRpcResponse(
                        id=request.id,
                        error={"code": -32603, "message": str(e)},
                    )
                    await self._transport.write_response(error_response)


def main() -> None:
    """Main entry point."""
    load_dotenv(override=False)
    server = ACPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
```

---

## ACP Adapter

**File**: `adapters/acp_adapter.py`

```python
"""ACP adapter for tool execution with status updates."""

from typing import Any, Callable, Awaitable
from transactoid.tools.registry import ToolRegistry
from transactoid.ui.acp.notifier import UpdateNotifier

class ACPAdapter:
    """Wrap tools to emit ACP updates during execution."""

    def __init__(
        self,
        registry: ToolRegistry,
        notifier: UpdateNotifier,
        session_id: str,
    ) -> None:
        self._registry = registry
        self._notifier = notifier
        self._session_id = session_id
        self._call_counter = 0

    def wrap_tool(self, tool: Tool) -> Callable[..., Awaitable[dict[str, Any]]]:
        """Wrap tool to emit ACP updates."""
        async def wrapped(**kwargs: Any) -> dict[str, Any]:
            # Generate tool call ID
            self._call_counter += 1
            call_id = f"call_{self._call_counter:03d}"

            # Notify: pending
            await self._notifier.tool_call(
                session_id=self._session_id,
                tool_call_id=call_id,
                title=tool.name,
                kind=self._get_kind(tool.name),
                status="pending",
            )

            # Notify: in_progress
            await self._notifier.tool_call_update(
                session_id=self._session_id,
                tool_call_id=call_id,
                status="in_progress",
            )

            # Execute
            try:
                result = tool.execute(**kwargs)
                status = "completed"
            except Exception as e:
                result = {"status": "error", "error": str(e)}
                status = "failed"

            # Notify: completed/failed
            await self._notifier.tool_call_update(
                session_id=self._session_id,
                tool_call_id=call_id,
                status=status,
                content=[{"type": "text", "text": str(result)}],
            )

            return result

        return wrapped

    def _get_kind(self, tool_name: str) -> str:
        """Map tool name to ACP kind."""
        kind_map = {
            "sync_transactions": "fetch",
            "run_sql": "execute",
            "recategorize_merchant": "edit",
            "tag_transactions": "edit",
        }
        return kind_map.get(tool_name, "other")
```

---

## Entry Point

**File**: `pyproject.toml` (add script)

```toml
[project.scripts]
transactoid = "transactoid.ui.cli:main"
transactoid-chatkit = "transactoid.ui.chatkit.server:main"
transactoid-mcp = "transactoid.ui.mcp.server:main"
transactoid-acp = "transactoid.ui.acp.server:main"  # NEW
```

---

## Testing Strategy

### Unit Tests

```python
# tests/ui/acp/test_transport.py
def test_read_message_parses_json_rpc():
    """Test JSON-RPC message parsing."""
    ...

def test_write_response_formats_correctly():
    """Test response formatting."""
    ...

# tests/ui/acp/test_handlers.py
async def test_initialize_returns_capabilities():
    """Test initialize handler returns correct capabilities."""
    result = await handle_initialize({"protocolVersion": 1})
    assert result["protocolVersion"] == 1
    assert "agentCapabilities" in result
    assert result["agentInfo"]["name"] == "transactoid"

async def test_session_new_creates_session():
    """Test session creation."""
    manager = SessionManager()
    session_id = manager.create(cwd="/home/user", mcp_servers=[])
    assert session_id.startswith("sess_")
    assert manager.get(session_id) is not None
```

### Integration Tests

```python
# tests/integration/test_acp_server.py
async def test_full_acp_flow():
    """Test full ACP session: init → new → prompt → updates."""
    # Mock stdin/stdout
    # Send initialize, verify response
    # Send session/new, verify session ID
    # Send session/prompt, verify updates received
    ...
```

---

## Success Criteria

1. **Protocol Compliance**
   - [ ] Initialize handshake with capability negotiation
   - [ ] Session creation and management
   - [ ] Prompt processing with streaming updates
   - [ ] Tool call status reporting (pending → in_progress → completed/failed)

2. **Integration**
   - [ ] Reuses existing ToolRegistry
   - [ ] Reuses existing services (DB, Taxonomy, etc.)
   - [ ] Works with VS Code/Cursor ACP extensions

3. **Quality**
   - [ ] mypy strict mode passes
   - [ ] ruff check passes
   - [ ] Unit tests for all handlers
   - [ ] Integration test for full flow

---

## Future Enhancements

1. **Permission Requests**: Implement `session/request_permission` for sensitive operations
2. **File System Callbacks**: Implement `fs/read_text_file`, `fs/write_text_file` for editor file access
3. **Terminal Integration**: Implement `terminal/*` methods for command execution
4. **Session Persistence**: Implement `session/load` for resuming sessions
5. **Authentication**: Add auth methods if needed for production deployments

---

## References

- [ACP Architecture](https://www.agentclientprotocol.com/overview/architecture)
- [ACP Initialization](https://www.agentclientprotocol.com/protocol/initialization)
- [ACP Session Setup](https://www.agentclientprotocol.com/protocol/session-setup)
- [ACP Tool Calls](https://www.agentclientprotocol.com/protocol/tool-calls)
- [ACP Schema](https://www.agentclientprotocol.com/protocol/schema)
- [ACP File System](https://www.agentclientprotocol.com/protocol/file-system)
- [ACP Terminals](https://www.agentclientprotocol.com/protocol/terminals)
