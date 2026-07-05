"""Modal Function that runs the secrets proxy (deploy artifact).

Holds the real LLM keys as a Modal Secret and serves :func:`build_proxy_app`.
Deploy with ``modal deploy deploy/sandbox/proxy/modal_app.py``; Fly then calls
``/admin/register`` per turn and the sandbox reaches ``/{path}`` with only a
capability token.

NOTE (single upstream): Penny runs Gemini, so this cut pins one upstream host.
Multi-provider routing (per-binding upstream host) is a follow-up — the binding
already carries the provider's auth header; adding ``upstream_base`` to it
generalizes this without touching the proxy core.

Registry durability: the proxy may run across several containers, so bindings
live in a shared ``modal.Dict`` — the ``register`` call and the sandbox's model
call can land on different replicas and still resolve the same token.
"""

from __future__ import annotations

import os

from core import Binding, build_proxy_app
import modal

app = modal.App("penny-secrets-proxy")


class ModalDictRegistry:
    """SessionRegistry backed by a shared ``modal.Dict`` (cross-container)."""

    def __init__(self) -> None:
        self._d = modal.Dict.from_name("penny-proxy-sessions", create_if_missing=True)

    def register(self, token: str, binding: Binding) -> None:
        self._d[token] = {
            "conversation_id": binding.conversation_id,
            "credential_ref": binding.credential_ref,
            "auth_header": binding.auth_header,
            "bearer": binding.bearer,
        }

    def revoke_conversation(self, conversation_id: str) -> None:
        for token, b in list(self._d.items()):
            if isinstance(b, dict) and b.get("conversation_id") == conversation_id:
                del self._d[token]

    def resolve(self, token: str | None) -> Binding | None:
        if not token:
            return None
        b = self._d.get(token)
        return Binding(**b) if isinstance(b, dict) else None

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi>=0.115", "httpx>=0.27", "uvicorn>=0.30"
).add_local_python_source("core")

# Modal Secret "penny-llm-keys" must carry GOOGLE_API_KEY (+ others) and
# PROXY_ADMIN_TOKEN (the shared admin secret Fly holds).
_KEY_BY_REF = {"gemini": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_UPSTREAM = "https://generativelanguage.googleapis.com"


@app.function(image=image, secrets=[modal.Secret.from_name("penny-llm-keys")])
@modal.asgi_app()
def proxy():  # noqa: ANN201 - Modal decorator provides the ASGI type
    registry = ModalDictRegistry()

    def key_resolver(ref: str) -> str:
        return os.environ[_KEY_BY_REF.get(ref, "GOOGLE_API_KEY")]

    return build_proxy_app(
        registry=registry,
        upstream_base=_UPSTREAM,
        key_resolver=key_resolver,
        admin_token=os.environ["PROXY_ADMIN_TOKEN"],
    )
