"""FastAPI app exposing POST /api/chat as a Vercel AI SDK UI message stream."""

from __future__ import annotations

import os
from typing import Any

from agent_harness.providers.google import GeminiModel
from agent_harness.sessions.inmemory import InMemorySession
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv(override=False)
# Import _logging first so the file sink is installed before anything
# downstream emits its first log line.
from penny import _logging  # noqa: E402, F401  side-effect: install file sink
from penny.agent_factory import build_agent, build_model  # noqa: E402
from penny.bootstrap import bootstrap  # noqa: E402

from .bridge import stream_and_persist  # noqa: E402
from .hydration import conversation_to_ui  # noqa: E402
from .persistence.rehydrate import parts_to_messages  # noqa: E402
from .persistence.store import ConversationStore  # noqa: E402

def _sandbox_flag() -> bool:
    return os.environ.get("PENNY_SANDBOX_TURNS", "").lower() in ("1", "true", "yes")


# The MCP tool server (built when the sandbox flag is on): same process as the
# token minting (sandbox_wiring.mcp_registry), so the capability registry is
# shared. The session manager's run() must be entered in the app lifespan
# because a mounted sub-app's own lifespan does not fire.
_mcp_app = None
_mcp_session_manager = None
if _sandbox_flag():
    from penny.api.mcp_server import create_mcp
    from penny.api.sandbox_wiring import mcp_registry
    from penny.plugins.amazon import build_amazon_toolset
    from penny.tools.registry import build_toolset

    _mcp_app, _mcp_session_manager = create_mcp([build_toolset(), build_amazon_toolset()], mcp_registry)


@__import__("contextlib").asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ANN201
    bootstrap()  # idempotent schema + taxonomy seed
    if _mcp_session_manager is not None:
        async with _mcp_session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="Penny backend", lifespan=_lifespan)
if _mcp_app is not None:
    app.mount("/mcp", _mcp_app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: GeminiModel | None = None
_conversation_store: ConversationStore | None = None


def _get_model() -> GeminiModel:
    global _model
    if _model is None:
        _model = build_model()
    return _model


def _get_conversation_store() -> ConversationStore:
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store


async def _seed_session(
    store: ConversationStore, conversation_id: str
) -> InMemorySession:
    """Build an in-memory session seeded with prior-turn context.

    Reverse-maps the conversation's stored ``parts`` into harness ``Message``s
    (``parts_to_messages``) and loads them into a fresh ``InMemorySession``.
    Called BEFORE the current user turn is appended, so the seed holds only
    prior turns; the loop appends the new prompt itself. With
    ``persist_session=False`` the agent reads this seed but writes nothing back
    — the app store is the single source of continuity.
    """
    rows = store.get_conversation_messages(conversation_id)
    prior_messages = parts_to_messages(rows)
    session = InMemorySession(session_id=conversation_id)
    if prior_messages:
        await session.add_messages(prior_messages)
    return session


def _text_from_message(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    )
    if text:
        return text
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _extract_user_message_id(body: dict[str, Any]) -> str | None:
    """Read the AI SDK message id of the inbound user turn, if present."""
    message = body.get("message")
    if isinstance(message, dict):
        mid = message.get("id")
        return mid if isinstance(mid, str) else None
    messages = body.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if isinstance(entry, dict) and entry.get("role") == "user":
                mid = entry.get("id")
                return mid if isinstance(mid, str) else None
    return None


def _extract_prompt(body: dict[str, Any]) -> str:
    """Read the latest user text from the AI SDK chat POST body.

    The real transport sends a single ``message``; fall back to a ``messages``
    array for other triggers.
    """
    message = body.get("message")
    if isinstance(message, dict):
        return _text_from_message(message)
    messages = body.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if isinstance(entry, dict) and entry.get("role") == "user":
                text = _text_from_message(entry)
                if text:
                    return text
    return ""


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Hydrate a conversation from the website store (the faithful path).

    Reads the captured ``conversation_messages`` rows — not the lossy harness
    transcript — so the rehydrated transcript matches what was streamed. (The
    ``/api/sessions`` path is kept for frontend compatibility; it now reads the
    conversation store.)
    """
    store = _get_conversation_store()
    rows = store.get_conversation_messages(session_id)
    return {"sessionId": session_id, "messages": conversation_to_ui(rows)}


_SSE_HEADERS = {
    "x-vercel-ai-ui-message-stream": "v1",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
}


def _sandbox_enabled() -> bool:
    return os.environ.get("PENNY_SANDBOX_TURNS", "").lower() in ("1", "true", "yes")


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    chat_id = str(body.get("id") or "default")
    prompt = _extract_prompt(body)
    user_message_id = _extract_user_message_id(body)

    store = _get_conversation_store()
    store.ensure_conversation(chat_id)

    # PRIOR-turn context, captured BEFORE the current user turn is appended.
    prior_messages = parts_to_messages(store.get_conversation_messages(chat_id))

    store.append_user_message(chat_id, ai_sdk_message_id=user_message_id, text=prompt)
    store.set_title_if_unset(chat_id, prompt)

    if _sandbox_enabled():
        # The loop runs in a per-conversation Modal sandbox; Fly renders the
        # prompt, seeds prior turns, and relays the sandbox's events.
        from penny.agent_factory import _render_system_prompt

        from .sandbox_wiring import sandboxed_stream_and_persist

        seed = [m.model_dump(mode="json") for m in prior_messages]
        return StreamingResponse(
            sandboxed_stream_and_persist(
                prompt=prompt,
                system_prompt=_render_system_prompt(),
                seed_messages=seed,
                store=store,
                conversation_id=chat_id,
            ),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    # In-process path (default): build the agent and stream it locally.
    session = InMemorySession(session_id=chat_id)
    if prior_messages:
        await session.add_messages(prior_messages)
    agent = build_agent(model=_get_model(), session=session, persist_session=False)
    return StreamingResponse(
        stream_and_persist(agent, prompt, store=store, conversation_id=chat_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/api/chat/{conversation_id}/cancel")
async def cancel_chat(conversation_id: str) -> dict[str, bool]:
    """Route a browser stop to the sandbox runner's cancel endpoint."""
    from .sandbox_wiring import cancel_active_run

    return {"cancelled": await cancel_active_run(conversation_id)}
