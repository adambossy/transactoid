"""Minimal async LLM client shared across penny.

Wraps the direct OpenAI / Gemini SDKs behind one public ``complete()`` call so
callers (the merchant normalizer today; other call sites later) don't each
reimplement client init and provider dispatch. Every call is traced via
``penny.observability``. Clients are created lazily on first use.
"""

from __future__ import annotations

import os
from typing import Literal

from penny import observability

Provider = Literal["openai", "gemini"]


def infer_provider(model: str | None) -> Provider | None:
    """Infer the provider from a model name, or None if ambiguous."""
    if not model:
        return None
    m = model.strip().lower()
    if m.startswith(("gemini", "google/")):
        return "gemini"
    if m.startswith(("gpt", "o", "openai/")):
        return "openai"
    return None


class LLMClient:
    """Lazily-initialized async client bound to a single (provider, model)."""

    def __init__(self, *, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model
        self._openai_client: object | None = None
        self._gemini_client: object | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> Provider:
        return self._provider

    async def complete(
        self, prompt: str, *, trace_name: str | None = None, json_mode: bool = False
    ) -> str:
        """Send ``prompt`` to the model and return the response text.

        ``json_mode`` requests a JSON response where the provider supports it
        (Gemini ``response_mime_type``). Raises ``RuntimeError`` if the
        provider's API key is missing.
        """
        if self._provider == "gemini":
            return await self._complete_gemini(prompt, trace_name, json_mode)
        return await self._complete_openai(prompt, trace_name, json_mode)

    def _trace_label(self, trace_name: str | None) -> str:
        return f"{trace_name}:{self._model}" if trace_name else self._model

    async def _complete_openai(
        self, prompt: str, trace_name: str | None, json_mode: bool
    ) -> str:
        if self._openai_client is None:
            from openai import AsyncOpenAI

            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")
            self._openai_client = AsyncOpenAI(api_key=api_key)

        # Enforce JSON output via the Responses API's text.format (mirrors the
        # categorizer); without it the model may return prose and parsing fails.
        extra_body = (
            {"text": {"format": {"type": "json_object"}}} if json_mode else None
        )
        with observability.llm_generation(
            self._trace_label(trace_name), model=self._model, input=prompt
        ) as gen:
            resp = await self._openai_client.responses.create(  # type: ignore[attr-defined]
                model=self._model,
                input=prompt,
                extra_body=extra_body,
            )
            text = getattr(resp, "output_text", None) or str(resp)
            gen.update(output=text)
            return text

    async def _complete_gemini(
        self, prompt: str, trace_name: str | None, json_mode: bool
    ) -> str:
        if self._gemini_client is None:
            from google.genai.client import Client

            api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY is required to call Gemini.")
            self._gemini_client = Client(api_key=api_key)

        from google.genai.types import GenerateContentConfig

        config = (
            GenerateContentConfig(response_mime_type="application/json")
            if json_mode
            else None
        )
        with observability.llm_generation(
            self._trace_label(trace_name), model=self._model, input=prompt
        ) as gen:
            resp = await self._gemini_client.aio.models.generate_content(  # type: ignore[attr-defined]
                model=self._model, contents=prompt, config=config
            )
            text = getattr(resp, "text", None) or str(resp)
            gen.update(output=text)
            return text
