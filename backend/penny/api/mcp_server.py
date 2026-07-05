"""MCP tool server — the trusted side where finance tools actually execute.

The sandboxed agent is an MCP *client*; agent-harness ships only that side, so
this server is ours. It exposes the existing penny toolsets (``build_toolset``,
``build_amazon_toolset``) over streamable-HTTP MCP with their tool names and
JSON schemas passed through verbatim, so tool identity is preserved. A
conversation-scoped **capability token** authenticates each request; the token
resolves to a principal that scopes tenancy where the tool runs — never in the
sandbox.

Segregation: this adapter lives in the website domain (``penny/api``) and is a
peer of ``bridge.py``. It imports agent-domain tools (the allowed website→agent
direction); the tools import nothing new.

Baseline note (main): this worktree is single-user, so the capability token
resolves to a dev principal and tenancy binding is a stub. The seam is shaped so
the account-creation branch drops in ``RequestContext`` + the ContextVar re-pin
without touching callers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
import json
import secrets
from typing import Any
import uuid

from agent_harness.core.tools import ToolCall
from agent_harness.core.toolsets import Toolset
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import mcp.types as mcp_types
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount

# ---------------------------------------------------------------------------
# Capability token registry (website-owned; in-memory for the main baseline).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """Who a capability token resolves to.

    ``ctx`` is the tenant ``RequestContext`` for the conversation (present when
    the account-creation auth stack is active); the MCP adapter re-pins it for
    the request so the tools run tenant-scoped exactly as a web-originated call.
    ``None`` in single-user/dev, where tools run unscoped.
    """

    conversation_id: str
    household_id: str | None = None
    user_id: str | None = None
    ctx: Any | None = None


class CapabilityRegistry:
    """Mint / resolve / revoke conversation-scoped MCP capability tokens."""

    def __init__(self) -> None:
        self._by_token: dict[str, Principal] = {}

    def mint(self, principal: Principal) -> str:
        token = secrets.token_urlsafe(32)
        self._by_token[token] = principal
        return token

    def register(self, token: str, principal: Principal) -> None:
        self._by_token[token] = principal

    def resolve(self, token: str | None) -> Principal | None:
        if not token:
            return None
        return self._by_token.get(token)

    def revoke(self, token: str) -> None:
        self._by_token.pop(token, None)


# The request-scoped principal, set by the auth middleware and read by tools
# (the seam where the account-creation RequestContext binds tenancy).
_principal: ContextVar[Principal | None] = ContextVar("mcp_principal", default=None)


def current_principal() -> Principal | None:
    return _principal.get()


# ---------------------------------------------------------------------------
# Tool index + MCP server over the penny toolsets.
# ---------------------------------------------------------------------------


class _ToolIndex:
    """Lazily-built name→(toolset, tool) map over the given toolsets."""

    def __init__(self, toolsets: list[Toolset]) -> None:
        self._toolsets = toolsets
        self._tools: dict[str, Any] | None = None
        self._owner: dict[str, Toolset] = {}

    async def _ensure(self) -> dict[str, Any]:
        if self._tools is None:
            tools: dict[str, Any] = {}
            for ts in self._toolsets:
                for tool in await ts.list_tools(None):
                    tools[tool.name] = tool
                    self._owner[tool.name] = ts
            self._tools = tools
        return self._tools

    async def list_mcp_tools(self) -> list[mcp_types.Tool]:
        tools = await self._ensure()
        return [
            mcp_types.Tool(
                name=t.name,
                description=t.description or "",
                inputSchema=t.schema or {"type": "object", "properties": {}},
            )
            for t in tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        await self._ensure()
        toolset = self._owner.get(name)
        if toolset is None:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=f"unknown tool: {name}")],
                isError=True,
            )
        call = ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments or {})
        result = await toolset.call_tool(None, call)
        return _to_mcp_result(result)


def _to_mcp_result(result: Any) -> mcp_types.CallToolResult:
    """Convert a harness ``ToolResult`` to an MCP ``CallToolResult``.

    Mirrors ``bridge._serialize_tool_output``: structured content rides
    ``structuredContent`` verbatim (+ a JSON text block for legacy readers);
    otherwise the content blocks' text is forwarded.
    """
    if result.error:
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=str(result.error))],
            isError=True,
        )
    if result.structured_content is not None:
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=json.dumps(result.structured_content, default=str))],
            structuredContent=result.structured_content
            if isinstance(result.structured_content, dict)
            else {"result": result.structured_content},
        )
    text = "\n".join(getattr(b, "text", "") for b in result.content)
    return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=text)])


def _build_server(index: _ToolIndex) -> Server:
    server: Server = Server("penny-tools")

    @server.list_tools()
    async def _list() -> list[mcp_types.Tool]:
        return await index.list_mcp_tools()

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        return await index.call(name, arguments)

    return server


# ---------------------------------------------------------------------------
# ASGI app: auth middleware + streamable-HTTP MCP transport.
# ---------------------------------------------------------------------------


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[len("bearer ") :].strip()
    return None


def create_mcp(
    toolsets: list[Toolset], registry: CapabilityRegistry
) -> tuple[Any, StreamableHTTPSessionManager]:
    """Build the MCP ASGI handler AND return its session manager.

    Returns the *raw* ASGI callable (not a Starlette sub-app) so the host can
    ``app.mount("/mcp", handler)`` it directly: a nested ``Mount("/")`` would
    redirect ``POST /mcp`` → ``/mcp/`` (307), which the MCP client — and a proxy
    that strips the trailing slash — cannot follow. The manager's ``run()`` must
    be entered by whoever hosts the handler (mounted sub-app lifespans don't
    fire); :func:`build_mcp_app` is the standalone variant for the unit test.
    """
    index = _ToolIndex(toolsets)
    server = _build_server(index)
    session_manager = StreamableHTTPSessionManager(app=server, event_store=None, stateless=True)

    async def _handle(scope: Any, receive: Any, send: Any) -> None:
        request = Request(scope, receive)
        principal = registry.resolve(_bearer(request))
        if principal is None:
            resp = JSONResponse({"error": "invalid or missing capability token"}, status_code=401)
            await resp(scope, receive, send)
            return
        token = _principal.set(principal)
        # Re-pin the tenant context so the tools (run_sql, sync, …) run scoped to
        # this conversation's household exactly as a web-originated call would.
        if principal.ctx is not None:
            from penny.tenancy.context import set_request_context

            set_request_context(principal.ctx)
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            _principal.reset(token)
            if principal.ctx is not None:
                from penny.tenancy.context import set_request_context

                set_request_context(None)

    return _handle, session_manager


def build_mcp_app(toolsets: list[Toolset], registry: CapabilityRegistry) -> Starlette:
    """Standalone (own-lifespan) MCP app — used by the unit test under uvicorn."""
    handle, session_manager = create_mcp(toolsets, registry)

    @contextlib.asynccontextmanager
    async def _lifespan(_: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(routes=[Mount("/", app=handle)], lifespan=_lifespan)
