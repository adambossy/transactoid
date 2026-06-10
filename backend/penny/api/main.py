"""FastAPI app exposing POST /api/chat as a Vercel AI SDK UI message stream."""

from __future__ import annotations

from typing import Any

from agent_harness.providers.google import GeminiModel
from agent_harness.sessions.sqlite import SqliteSession
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
from penny.workspace import resolve_workspace_dir  # noqa: E402

from .bridge import stream_agent  # noqa: E402
from .hydration import messages_to_ui  # noqa: E402

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
_sessions: dict[str, SqliteSession] = {}


def _get_model() -> GeminiModel:
    global _model
    if _model is None:
        _model = build_model()
    return _model


def _get_session(chat_id: str) -> SqliteSession:
    """One durable SQLite-backed session per chat id.

    All sessions share one DB file in the workspace; the in-process dict
    only caches open connections (history survives restarts regardless).
    """
    session = _sessions.get(chat_id)
    if session is None:
        workspace = resolve_workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)
        session = SqliteSession(session_id=chat_id, path=workspace / "sessions.db")
        _sessions[chat_id] = session
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
    """Hydrate a conversation: persisted harness messages as UIMessages."""
    session = _get_session(session_id)
    messages = await session.get_messages()
    return {"sessionId": session_id, "messages": messages_to_ui(messages)}


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    chat_id = str(body.get("id") or "default")
    prompt = _extract_prompt(body)

    session = _get_session(chat_id)
    agent = build_agent(model=_get_model(), session=session)

    return StreamingResponse(
        stream_agent(agent, prompt),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )
