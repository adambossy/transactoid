"""Wire the sandboxed chat path into the FastAPI app (behind the flag).

Holds the process-global sandbox provider + store, mints/registers a proxy
capability token per turn, builds the ``TurnPayload`` (system prompt rendered
here on Fly, tenant-scoped), then dispatches the turn to a Modal sandbox and
relays its events — reusing the existing ``MessageAccumulator`` + ``_translate``
+ persistence so the browser frames and the stored transcript are identical to
the in-process path. Tenancy is threaded through: the MCP capability token
carries the turn's ``RequestContext`` so tools run scoped to the household, and
persistence is ctx-scoped.

Everything secret-shaped is read from env, never hardcoded:
    PENNY_SANDBOX_IMAGE   the published runner image id
    PENNY_SANDBOX_APP     Modal app name (default penny-sandbox)
    PENNY_PROXY_URL       the deployed secrets-proxy base URL
    PENNY_PROXY_ADMIN     the proxy admin token (shared Fly↔proxy secret)
    PENNY_MCP_PUBLIC_URL  optional: public URL of Fly's MCP server (enables tools)

Billing note: the proxy currently injects the platform Gemini key. Threading a
BYO/subsidy ``credential`` through to the proxy (and usage metering back to the
ledger) for sandboxed turns is a follow-up; the pre-dispatch billing *gate*
(Blocked → connect prompt) already runs in ``main.chat`` before we get here.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from loguru import logger
from protocol.events import decode_envelope

from agent_harness.core.credentials import Credential
from agent_harness.core.events import RunEnd, RunStart
from penny.agent_factory import _render_system_prompt
from penny.sandboxes.provider import ModalSandboxProvider
from penny.sandboxes.reaper import dispatch_turn, on_turn_end
from penny.sandboxes.store import InMemorySandboxStore
from penny.tenancy.context import RequestContext, set_request_context

from .accumulator import MessageAccumulator
from .bridge import _safe_persist, _sse, _translate
from .mcp_server import CapabilityRegistry, Principal
from .persistence.store import ConversationStore

_provider: ModalSandboxProvider | None = None
_sandbox_store = InMemorySandboxStore()
# MCP capability registry, shared with the mounted MCP server (tools path).
mcp_registry = CapabilityRegistry()
# conversation_id -> (tunnel_url, run_id) for the cancel endpoint.
_active_runs: dict[str, tuple[str, str]] = {}


def get_provider() -> ModalSandboxProvider:
    global _provider
    if _provider is None:
        image = os.environ["PENNY_SANDBOX_IMAGE"]
        _provider = ModalSandboxProvider(os.environ.get("PENNY_SANDBOX_APP", "penny-sandbox"), image)
    return _provider


async def _register_proxy_session(conversation_id: str) -> tuple[str, str]:
    """Mint a capability token and register it with the proxy. Returns
    (proxy_url, token)."""
    proxy_url = os.environ["PENNY_PROXY_URL"].rstrip("/")
    token = secrets.token_urlsafe(32)
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            f"{proxy_url}/admin/register",
            headers={"x-admin-token": os.environ["PENNY_PROXY_ADMIN"]},
            json={"token": token, "conversation_id": conversation_id, "credential_ref": "gemini"},
        )
        r.raise_for_status()
    return proxy_url, token


def _build_payload(
    conversation_id: str,
    prompt: str,
    system_prompt: str,
    seed_messages: list[dict[str, Any]],
    proxy_url: str,
    proxy_token: str,
    ctx: RequestContext,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "seed_messages": seed_messages,
        "model": {
            "provider": "google",
            "name": "gemini-3.5-flash",
            "base_url": proxy_url,
            "capability_token": proxy_token,
            "thinking_budget": -1,
        },
    }
    mcp_url = os.environ.get("PENNY_MCP_PUBLIC_URL")
    if mcp_url:
        # The MCP token carries the tenant context so tools run household-scoped.
        mcp_token = mcp_registry.mint(
            Principal(
                conversation_id=conversation_id,
                household_id=str(ctx.household_id),
                user_id=str(ctx.user_id),
                ctx=ctx,
            )
        )
        payload["mcp"] = {"url": mcp_url.rstrip("/"), "token": mcp_token}
    return payload


async def sandboxed_stream_and_persist(
    *,
    store: ConversationStore,
    conversation_id: str,
    ctx: RequestContext,
    prompt: str,
    seed_messages: list[dict[str, Any]],
    credential: Credential | None = None,
) -> AsyncIterator[str]:
    """Dispatch a Modal sandbox, run the turn, relay+persist (ctx-scoped)."""
    del credential  # billing credential-through-proxy is a follow-up (see module note)

    provider = get_provider()
    rec = _sandbox_store.get(conversation_id)
    system_prompt = _render_system_prompt(ctx)

    acc = MessageAccumulator()
    open_text: set[str] = set()
    finalized = False
    http = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=15.0))
    try:
        proxy_url, proxy_token = await _register_proxy_session(conversation_id)
        payload = _build_payload(
            conversation_id, prompt, system_prompt, seed_messages, proxy_url, proxy_token, ctx
        )
        handle = await dispatch_turn(rec, provider, now=time.time())
        start = await http.post(f"{handle.tunnel_url.rstrip('/')}/turns", json=payload)
        start.raise_for_status()
        run_id = start.json()["run_id"]
        _active_runs[conversation_id] = (handle.tunnel_url, run_id)

        url = f"{handle.tunnel_url.rstrip('/')}/runs/{run_id}/events"
        async with http.stream("GET", url, params={"from_seq": 0}) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: ") :]
                if data.strip() == "[DONE]":
                    break
                _seq, event = decode_envelope(json.loads(data))
                acc.consume(event)
                if isinstance(event, RunStart):
                    _safe_persist(store, conversation_id, ctx, acc, "streaming")
                try:
                    frames = _translate(event, open_text)
                except Exception as exc:  # noqa: BLE001
                    frames = [{"type": "error", "errorText": f"stream translation failed: {exc}"}]
                for frame in frames:
                    yield _sse(frame)
                if isinstance(event, RunEnd):
                    _safe_persist(store, conversation_id, ctx, acc, acc.status)
                    finalized = True
    except Exception as exc:  # noqa: BLE001 - surface transport/dispatch failure
        logger.bind(conversation_id=conversation_id).warning("sandboxed turn failed: {}", exc)
        yield _sse({"type": "error", "errorText": str(exc)})
    finally:
        if not finalized:
            _safe_persist(store, conversation_id, ctx, acc, "error")
        _active_runs.pop(conversation_id, None)
        await on_turn_end(rec, now=time.time())
        await http.aclose()
        set_request_context(None)  # streaming task ran in a context copy
    yield "data: [DONE]\n\n"


async def cancel_active_run(conversation_id: str) -> bool:
    """Route a browser stop to the runner's cancel endpoint."""
    entry = _active_runs.get(conversation_id)
    if entry is None:
        return False
    tunnel_url, run_id = entry
    async with httpx.AsyncClient(timeout=30.0) as c:
        await c.post(f"{tunnel_url.rstrip('/')}/runs/{run_id}/cancel")
    return True
