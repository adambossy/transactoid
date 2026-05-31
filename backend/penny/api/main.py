"""FastAPI app exposing POST /api/chat as a Vercel AI SDK UI message stream."""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent_harness.providers.openai import OpenAIResponsesModel
from agent_harness.sessions.inmemory import InMemorySession

from ..agent_factory import build_agent, build_model
from ..bootstrap import bootstrap
from .bridge import stream_agent

load_dotenv(override=False)

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

_model: OpenAIResponsesModel | None = None
_sessions: dict[str, InMemorySession] = {}


def _get_model() -> OpenAIResponsesModel:
    global _model
    if _model is None:
        _model = build_model()
    return _model


def _text_from_message(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    text = "".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") == "text"
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


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body: dict[str, Any] = await request.json()
    chat_id = str(body.get("id") or "default")
    prompt = _extract_prompt(body)

    session = _sessions.setdefault(chat_id, InMemorySession(session_id=chat_id))
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
