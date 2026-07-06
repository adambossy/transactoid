"""Build a harness ``Agent`` from a ``TurnPayload`` — harness classes only.

The runner never imports ``penny``: everything conversation-specific arrives in
the payload. Tools execute on Fly behind MCP (so the sandbox holds no DB
credential); the model provider is pointed at the secrets proxy. This module is
the seam that turns declarative payload into a live agent.

NOTE (provider gap): ``GoogleProvider`` accepts ``base_url`` but silently
ignores it — to route Gemini through the proxy the runner builds the ``genai``
client itself and injects it via ``client=``. Anthropic/OpenAI honor
``base_url`` directly. The one-line upstream fix retires the Google branch.
"""

from __future__ import annotations

from typing import Any

from agent_harness import Agent, MCPServerHTTP
from agent_harness.core.models import Message
from agent_harness.sessions import InMemorySession
from protocol.turn import TurnPayload


async def _seed_session(payload: TurnPayload) -> InMemorySession:
    session = InMemorySession(session_id=payload.conversation_id)
    messages: list[Message] = []
    for raw in payload.seed_messages:
        # seed_messages are encoded harness Messages (``{"__pyd__", "d"}``) or
        # already-dumped Message dicts; accept both.
        data = raw.get("d", raw) if isinstance(raw, dict) else raw
        messages.append(Message.model_validate(data))
    if messages:
        # ``add_messages`` is the Session API: async, batched, list-typed.
        await session.add_messages(messages)
    return session


def _build_model(payload: TurnPayload) -> Any:
    cfg = payload.model
    token = cfg.capability_token or "proxy-capability-placeholder"
    if cfg.provider == "anthropic":
        from agent_harness.providers.anthropic import AnthropicModel, AnthropicProvider

        provider = AnthropicProvider(api_key=token, base_url=cfg.base_url)
        return AnthropicModel(provider=provider, name=cfg.name)
    if cfg.provider == "openai":
        from agent_harness.providers.openai import OpenAIModel, OpenAIProvider

        provider = OpenAIProvider(api_key=token, base_url=cfg.base_url)
        return OpenAIModel(provider=provider, name=cfg.name)
    # google / default — inject a genai client pinned at the proxy base_url
    # (GoogleProvider accepts base_url but does not apply it, so build the
    # client ourselves).
    from agent_harness.providers.google import GeminiModel, GoogleProvider

    client = None
    if cfg.base_url:
        from google import genai
        from google.genai.types import HttpOptions

        client = genai.Client(
            api_key=token, http_options=HttpOptions(base_url=cfg.base_url)
        )
    provider = GoogleProvider(api_key=token, client=client)
    return GeminiModel(provider=provider, name=cfg.name)


async def build_agent(payload: TurnPayload) -> Agent:
    """Assemble the per-turn agent: model @ proxy, tools @ MCP, seeded session."""
    toolsets: list[Any] = []
    if payload.mcp is not None:

        async def _auth() -> dict[str, str]:
            return {"Authorization": f"Bearer {payload.mcp.token}"}

        toolsets.append(MCPServerHTTP("penny-tools", payload.mcp.url, auth=_auth))

    return Agent(
        name="penny",
        model=_build_model(payload),
        instructions=payload.system_prompt,
        toolsets=toolsets,
        session=await _seed_session(payload),
        persist_session=False,
    )
