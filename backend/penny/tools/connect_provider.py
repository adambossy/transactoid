"""Agent tool: surface the 'Connect a provider' card in chat.

Returns **static** provider options only — no secret, no billing/website import
(agent code must not reach into the website domain). The inline card (frontend,
registered to this tool's name) drives the actual connect flow against the
website routes (``POST /api/providers/{provider}/key``,
``GET /api/providers/{provider}/oauth/start``) and reads runway from
``GET /api/me/billing``. This keeps the agent/website segregation intact: the
tool only tells the UI *what* to render.
"""

from __future__ import annotations

from typing import Any

from agent_harness import tool

# Providers a user can bring a key for. OAuth is offered only where a client is
# registered (config-driven on the website side); the card resolves that.
_PROVIDERS = [
    {"id": "google", "label": "Google (Gemini) API key", "kind": "api_key"},
    {"id": "openai", "label": "OpenAI API key", "kind": "api_key"},
    {"id": "anthropic", "label": "Anthropic API key", "kind": "api_key"},
]


@tool
async def connect_provider() -> dict[str, Any]:
    """Offer the user a card to connect their own AI provider credentials.

    Use when the user's free Penny credits are low/exhausted, or when they ask
    to use their own API key or subscription. Returns the provider options for
    the inline connect card; the card handles entry + storage securely (the key
    is never shown again).
    """
    return {
        "type": "connect_provider",
        "providers": _PROVIDERS,
        "settings_url": "/settings/providers",
    }
