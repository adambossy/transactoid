"""FastAPI app exposing POST /api/chat as a Vercel AI SDK UI message stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agent_harness.providers.google import GeminiModel
from agent_harness.sessions.inmemory import InMemorySession
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv(override=False)
# Import _logging first so the file sink is installed before anything
# downstream emits its first log line.
from penny import _logging  # noqa: E402, F401  side-effect: install file sink
from penny.agent_factory import build_agent, build_model  # noqa: E402
from penny.bootstrap import bootstrap  # noqa: E402
from penny.tenancy.context import (  # noqa: E402
    reset_request_context,
    set_request_context,
)
from penny.tenancy.principal import resolve_dev_principal  # noqa: E402

from .bridge import stream_and_persist  # noqa: E402
from .hydration import conversation_to_ui  # noqa: E402
from .persistence.rehydrate import parts_to_messages  # noqa: E402
from .persistence.store import ConversationStore  # noqa: E402

app = FastAPI(title="Penny backend")


@app.on_event("startup")
async def _on_startup() -> None:
    """Create the schema + seed the taxonomy on first boot. Idempotent."""
    bootstrap()


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


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    chat_id = str(body.get("id") or "default")
    prompt = _extract_prompt(body)
    user_message_id = _extract_user_message_id(body)

    # Resolve the requesting principal (dev stub: headers, then PENNY_DEV_*
    # env; replaced by real auth in phase 2) and pin it on the ContextVar so
    # every DB session in this request — including the agent's tools — is
    # tenant-scoped. Reset when the stream finishes, below.
    try:
        principal = resolve_dev_principal(dict(request.headers))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    context_token = set_request_context(principal)

    store = _get_conversation_store()
    store.ensure_conversation(chat_id)

    # Seed the agent with PRIOR-turn context from the app store BEFORE the
    # current user turn is appended, so the seed excludes this turn (the loop
    # appends the new prompt itself). This is what makes persist_session=False
    # safe: the model still sees earlier turns.
    session = await _seed_session(store, chat_id)

    # Persist the user turn up front (before any assistant frame) so it is
    # durable even if the client disconnects mid-stream. Creation is lazy.
    store.append_user_message(chat_id, ai_sdk_message_id=user_message_id, text=prompt)
    # Derive a title from the first user message (internal write, no endpoint).
    store.set_title_if_unset(chat_id, prompt)

    # persist_session=False: the harness never writes to sessions.db; the app
    # store (above + the bridge) is the single persistence layer. The seeded
    # session provides read-only continuity.
    agent = build_agent(
        model=_get_model(), session=session, persist_session=False, ctx=principal
    )

    async def _scoped_stream() -> AsyncIterator[str]:
        try:
            async for frame in stream_and_persist(
                agent, prompt, store=store, conversation_id=chat_id
            ):
                yield frame
        finally:
            reset_request_context(context_token)

    return StreamingResponse(
        _scoped_stream(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )
