"""Secrets-proxy core — the auth gates and key injection, framework-only.

Pure FastAPI + httpx so it is unit-testable without Modal. The Modal Function
(``modal_app.py``) wraps this: it holds the real LLM API keys as Modal Secrets
and hands them to :func:`build_proxy_app` via ``key_resolver``. The sandbox
authenticates with a conversation-scoped **capability token**; the proxy strips
it, injects the real vendor key at the egress boundary, and streams the response
back. A leaked capability token can only spend this conversation's bound
credential, within its limits, and is revocable instantly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

# Only these upstream paths may be proxied (Gemini + Anthropic + OpenAI chat).
_ALLOWED_PATH_SUFFIXES = (
    ":generateContent",
    ":streamGenerateContent",
    "/v1/messages",
    "/v1/chat/completions",
    "/v1/responses",
)


@dataclass
class Binding:
    """What a capability token is allowed to do."""

    conversation_id: str
    credential_ref: str  # names a real key the resolver can produce
    # Vendor auth header the real key goes into ("x-goog-api-key", "x-api-key",
    # or "authorization" for a Bearer). Chosen by the provider Fly registered.
    auth_header: str = "x-goog-api-key"
    bearer: bool = False


@dataclass
class SessionRegistry:
    """Conversation-scoped capability tokens → bindings (Fly is the admin)."""

    _by_token: dict[str, Binding] = field(default_factory=dict)

    def register(self, token: str, binding: Binding) -> None:
        self._by_token[token] = binding

    def revoke_conversation(self, conversation_id: str) -> None:
        for tok in [t for t, b in self._by_token.items() if b.conversation_id == conversation_id]:
            self._by_token.pop(tok, None)

    def resolve(self, token: str | None) -> Binding | None:
        return self._by_token.get(token) if token else None


def _path_allowed(path: str) -> bool:
    # Starlette's ``{path:path}`` strips the leading slash; normalize so the
    # ``/v1/...`` allowlist entries match regardless.
    full = "/" + path.lstrip("/")
    return any(full.endswith(sfx) or sfx in full for sfx in _ALLOWED_PATH_SUFFIXES)


def _extract_token(request: Request) -> str | None:
    """The capability token arrives in whichever header the vendor client uses
    for auth: ``Authorization: Bearer`` (OpenAI), ``x-api-key`` (Anthropic), or
    ``x-goog-api-key`` (Gemini). Tokens are globally unique, so accept any.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-goog-api-key") or request.headers.get("x-api-key")


def build_proxy_app(
    *,
    registry: SessionRegistry,
    upstream_base: str,
    key_resolver: Callable[[str], str],
    admin_token: str,
    client: httpx.AsyncClient | None = None,
    usage_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> FastAPI:
    """Build the proxy ASGI app. ``key_resolver(credential_ref) -> real key``."""
    app = FastAPI(title="penny-secrets-proxy")
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))

    # --- Admin plane (only Fly, via a proxy-auth token) ---------------------

    def _admin_ok(request: Request) -> bool:
        return request.headers.get("x-admin-token") == admin_token

    @app.post("/admin/register")
    async def register(request: Request) -> JSONResponse:
        if not _admin_ok(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        registry.register(
            body["token"],
            Binding(
                conversation_id=body["conversation_id"],
                credential_ref=body["credential_ref"],
                auth_header=body.get("auth_header", "x-goog-api-key"),
                bearer=body.get("bearer", False),
            ),
        )
        return JSONResponse({"ok": True})

    @app.post("/admin/revoke")
    async def revoke(request: Request) -> JSONResponse:
        if not _admin_ok(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        registry.revoke_conversation(body["conversation_id"])
        return JSONResponse({"ok": True})

    # --- Data plane (the sandbox's model calls) -----------------------------

    @app.api_route("/{path:path}", methods=["POST", "GET"])
    async def proxy(path: str, request: Request) -> Any:
        if not _path_allowed(path):
            return JSONResponse({"error": "path not allowed"}, status_code=404)
        binding = registry.resolve(_extract_token(request))
        if binding is None:
            return JSONResponse({"error": "invalid or revoked capability token"}, status_code=401)

        real_key = key_resolver(binding.credential_ref)
        # Rebuild headers: drop the capability bearer, inject the real key.
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"authorization", "host", "content-length", binding.auth_header.lower()}
        }
        headers[binding.auth_header] = f"Bearer {real_key}" if binding.bearer else real_key

        body = await request.body()
        url = f"{upstream_base.rstrip('/')}/{path}"
        params = dict(request.query_params)
        upstream = await http.request(
            request.method, url, headers=headers, content=body, params=params
        )
        if usage_sink is not None:
            usage_sink(binding.conversation_id, {"status": upstream.status_code})

        return StreamingResponse(
            iter([upstream.content]),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    return app
