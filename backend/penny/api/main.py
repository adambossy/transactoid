"""FastAPI app exposing POST /api/chat as a Vercel AI SDK UI message stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
from typing import Any

from agent_harness.providers.google import GeminiModel
from agent_harness.sessions.inmemory import InMemorySession
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv(override=False)
# Import _logging first so the file sink is installed before anything
# downstream emits its first log line.
from penny import _logging  # noqa: E402, F401  side-effect: install file sink
from penny.agent_factory import build_agent, build_model  # noqa: E402
from penny.auth.settings import load_auth_settings  # noqa: E402
from penny.bootstrap import bootstrap  # noqa: E402
from penny.db import get_db  # noqa: E402
from penny.tenancy.context import (  # noqa: E402
    RequestContext,
    SessionMode,
    set_request_context,
)
from penny.workspace_store.blobs import R2BlobStore  # noqa: E402
from penny.workspace_store.broker import ensure_prefixes  # noqa: E402
from penny.workspace_store.sync import flush, materialize  # noqa: E402

from .auth import request_context  # noqa: E402
from .bridge import stream_and_persist  # noqa: E402
from .hydration import conversation_to_ui  # noqa: E402
from .persistence.rehydrate import parts_to_messages  # noqa: E402
from .persistence.store import ConversationAccessError, ConversationStore  # noqa: E402

app = FastAPI(title="Penny backend")


@app.on_event("startup")
async def _on_startup() -> None:
    """Create the schema + seed the taxonomy on first boot. Idempotent."""
    bootstrap()


# Fail closed at import: clerk mode requires issuer/JWKS/frontend-origin (the
# origin also feeds CORS). Never `*` with credentials.
_auth_settings = load_auth_settings()
_origins = ["http://localhost:5173"]
if _auth_settings.frontend_origin:
    _origins.append(_auth_settings.frontend_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
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
    store: ConversationStore, conversation_id: str, ctx: RequestContext
) -> InMemorySession:
    """Build an in-memory session seeded with prior-turn context.

    Reverse-maps the conversation's stored ``parts`` into harness ``Message``s
    (``parts_to_messages``) and loads them into a fresh ``InMemorySession``.
    Called BEFORE the current user turn is appended, so the seed holds only
    prior turns; the loop appends the new prompt itself. With
    ``persist_session=False`` the agent reads this seed but writes nothing back
    — the app store is the single source of continuity.
    """
    rows = store.get_conversation_messages(conversation_id, ctx)
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


def _turn_context(ctx: RequestContext, *, conversation_mode: str) -> RequestContext:
    """Adopt the conversation's stored session mode for this turn.

    Identity (user/household) still comes only from the verified principal; the
    mode comes from the immutable conversation row. A ``joint`` turn runs RLS
    with the nil-user sentinel (shared-only) via ``effective_user_id``.
    """
    return replace(ctx, session_mode=SessionMode(conversation_mode))


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    """Hydrate a conversation from the website store (the faithful path).

    Reads the captured ``conversation_messages`` rows — not the lossy harness
    transcript — so the rehydrated transcript matches what was streamed. (The
    ``/api/sessions`` path is kept for frontend compatibility; it now reads the
    conversation store.)
    """
    store = _get_conversation_store()
    # Ownership is checked before any content is returned (closes the IDOR):
    # a conversation the principal cannot see (or that does not exist) is a 404.
    try:
        rows = store.get_conversation_messages(session_id, ctx)
    except ConversationAccessError:
        raise HTTPException(status_code=404, detail="not found") from None
    return {"sessionId": session_id, "messages": conversation_to_ui(rows)}


@app.post("/api/chat")
async def chat(
    request: Request,
    ctx: RequestContext = Depends(request_context),
) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    chat_id = str(body.get("id") or "default")
    prompt = _extract_prompt(body)
    user_message_id = _extract_user_message_id(body)

    store = _get_conversation_store()
    # ``sessionMode`` from the body is honored ONLY when creating a new
    # conversation; on an existing one the store ignores it (mode is immutable).
    requested = str(body.get("sessionMode") or "individual")
    try:
        conv = store.ensure_conversation(chat_id, ctx, session_mode=requested)
    except ConversationAccessError:
        raise HTTPException(status_code=404, detail="not found") from None
    except ValueError as exc:  # invalid sessionMode from the client
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Rebuild the turn's context from the conversation's STORED mode (not the
    # request), so a joint thread always runs shared-only regardless of the
    # body. Re-pin it here so the streaming task (which runs in a COPY of this
    # context) also sees it; every DB session — including the agent's tools —
    # is thus tenant-scoped. Cleared when the stream ends.
    turn_ctx = _turn_context(ctx, conversation_mode=conv.session_mode)
    set_request_context(turn_ctx)

    # Seed the agent with PRIOR-turn context from the app store BEFORE the
    # current user turn is appended, so the seed excludes this turn (the loop
    # appends the new prompt itself). This is what makes persist_session=False
    # safe: the model still sees earlier turns.
    session = await _seed_session(store, chat_id, turn_ctx)

    # Persist the user turn up front (before any assistant frame) so it is
    # durable even if the client disconnects mid-stream. Creation is lazy.
    store.append_user_message(
        chat_id, turn_ctx, ai_sdk_message_id=user_message_id, text=prompt
    )
    # Derive a title from the first user message (internal write, no endpoint).
    store.set_title_if_unset(chat_id, prompt)

    async def _scoped_stream() -> AsyncIterator[str]:
        # The response body is iterated in a different task context than the
        # handler that set the ContextVar (which the streaming task inherits
        # as a copy), so token-based reset would raise "created in a different
        # Context" — clear the principal instead.
        #
        # Phase 1b workspace lifecycle: materialize the turn's readable
        # prefixes into a per-run temp checkout, build the agent rooted there
        # (so its memory/reports edits are local-FS fast), stream the turn,
        # then flush changed blobs + advance each prefix head on success. A
        # streaming SSE generator can't be expressed as run_with_workspace's
        # ``await run_fn(root)`` shape, so the same materialize/flush primitives
        # are composed inline here; an aborted stream never reaches flush. The
        # workspace is scoped by turn_ctx, so a joint thread materializes
        # shared-only prefixes, consistent with the rest of the turn.
        blob_store = R2BlobStore()
        root = Path(tempfile.mkdtemp(prefix="penny-ws-"))
        db = get_db()
        try:
            with db.session_for(turn_ctx) as s:
                ensure_prefixes(s, turn_ctx)
                checkout = materialize(s, turn_ctx, blob_store=blob_store, root=root)
            # persist_session=False: the harness never writes to sessions.db;
            # the app store (above + the bridge) is the single persistence
            # layer. The seeded session provides read-only continuity.
            agent = build_agent(
                model=_get_model(),
                session=session,
                persist_session=False,
                ctx=turn_ctx,
                workspace_dir=checkout.root,
            )
            async for frame in stream_and_persist(
                agent, prompt, store=store, conversation_id=chat_id, ctx=turn_ctx
            ):
                yield frame
            with db.session_for(turn_ctx) as s:
                flush(s, turn_ctx, checkout, blob_store=blob_store)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            set_request_context(None)

    return StreamingResponse(
        _scoped_stream(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )
