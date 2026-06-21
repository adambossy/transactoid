"""LLM-backed merchant normalizer.

Mirrors the categorizer's provider/model resolution and direct-SDK call pattern,
but for descriptor → :class:`NormalizedMerchant` extraction driven by the
natural-language rule repository (``rules.yaml``).

Model resolution order (first non-empty wins):
1. explicit ``model`` argument
2. ``PENNY_NORMALIZER_MODEL`` env var
3. ``PENNY_CATEGORIZER_MODEL`` env var
4. ``PENNY_AGENT_MODEL`` (via core runtime config)
5. provider default
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from penny import observability
from penny.config import load_runtime_config_from_env
from penny.normalizer.core import KNOWN_CHANNELS, NormalizedMerchant, naive_normalize
from penny.normalizer.rules import build_system_prompt, load_rules

_Provider = Literal["openai", "gemini"]


class _ExtractionResult(BaseModel):
    idx: int = Field(..., description="Index matching the input descriptor")
    channel: str = Field(..., description="Resolved channel")
    normalized_name: str = Field(..., description="Stable identity slug")
    display_name: str = Field("", description="Human-facing label")
    counterparty: str | None = Field(None, description="Counterparty or null")


class _ExtractionResponse(BaseModel):
    results: list[_ExtractionResult]


def _sanitize_name(value: str) -> str:
    """Constrain an LLM-returned identity to a lowercase ``channel:slug`` shape."""
    lowered = value.strip().lower()
    # Keep alphanumerics, colons and hyphens; collapse everything else to '-'.
    cleaned = re.sub(r"[^a-z0-9:-]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-:")
    return cleaned or "unknown"


def _infer_provider(model: str | None) -> _Provider | None:
    if not model:
        return None
    m = model.strip().lower()
    if m.startswith(("gemini", "google/")):
        return "gemini"
    if m.startswith(("gpt", "o", "openai/")):
        return "openai"
    return None


class MerchantNormalizer:
    """Normalize descriptors into :class:`NormalizedMerchant` via an LLM."""

    def __init__(
        self,
        *,
        provider: _Provider | None = None,
        model: str | None = None,
        batch_size: int = 40,
        max_concurrency: int = 6,
    ) -> None:
        self._provider, self._model = self._resolve(provider, model)
        self._batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._system_prompt = build_system_prompt(load_rules())
        self._openai_client: object | None = None
        self._gemini_client: object | None = None

    @property
    def model(self) -> str:
        return self._model

    def _resolve(
        self, provider: _Provider | None, model: str | None
    ) -> tuple[_Provider, str]:
        norm_model = os.environ.get("PENNY_NORMALIZER_MODEL", "").strip() or None
        cat_model = os.environ.get("PENNY_CATEGORIZER_MODEL", "").strip() or None
        chosen = model or norm_model or cat_model
        inferred = _infer_provider(chosen)
        try:
            runtime = load_runtime_config_from_env()
            resolved_model = chosen or runtime.model
        except Exception:
            resolved_model = chosen or "gpt-5.5"
        resolved_provider = (
            provider or inferred or _infer_provider(resolved_model) or "openai"
        )
        if resolved_provider not in ("openai", "gemini"):
            resolved_provider = "openai"
        return resolved_provider, resolved_model

    # -- public API ---------------------------------------------------------

    async def normalize(self, descriptor: str) -> NormalizedMerchant:
        result = await self.normalize_many([descriptor])
        return result[descriptor]

    async def normalize_many(
        self, descriptors: list[str]
    ) -> dict[str, NormalizedMerchant]:
        """Resolve a list of descriptors (deduped, batched)."""
        unique = list(dict.fromkeys(d for d in descriptors if d is not None))
        if not unique:
            return {}

        batches = [
            unique[i : i + self._batch_size]
            for i in range(0, len(unique), self._batch_size)
        ]
        extracted = await asyncio.gather(
            *(self._extract_batch(batch) for batch in batches)
        )
        resolved: dict[str, NormalizedMerchant] = {}
        for batch_result in extracted:
            resolved.update(batch_result)
        return resolved

    # -- extraction ---------------------------------------------------------

    async def _extract_batch(
        self, descriptors: list[str]
    ) -> dict[str, NormalizedMerchant]:
        prompt = self._build_prompt(descriptors)
        try:
            raw = await self._call_llm(prompt)
            parsed = _ExtractionResponse.model_validate_json(self._extract_json(raw))
        except Exception as exc:  # noqa: BLE001 — degrade gracefully to naive
            logger.warning("normalizer LLM batch failed ({}); using naive", exc)
            return {d: naive_normalize(d) for d in descriptors}

        by_idx = {r.idx: r for r in parsed.results}
        out: dict[str, NormalizedMerchant] = {}
        for idx, descriptor in enumerate(descriptors):
            result = by_idx.get(idx)
            out[descriptor] = self._to_merchant(descriptor, result)
        return out

    def _to_merchant(
        self, descriptor: str, result: _ExtractionResult | None
    ) -> NormalizedMerchant:
        if result is None:
            return naive_normalize(descriptor)
        channel = result.channel.strip().lower()
        if channel not in KNOWN_CHANNELS or channel == "direct":
            return naive_normalize(descriptor)
        counterparty = (result.counterparty or "").strip() or None
        return NormalizedMerchant(
            normalized_name=_sanitize_name(result.normalized_name),
            display_name=(result.display_name or descriptor).strip(),
            source_channel=channel,
            counterparty=counterparty,
        )

    def _build_prompt(self, descriptors: list[str]) -> str:
        numbered = "\n".join(f"{i}\t{d}" for i, d in enumerate(descriptors))
        return (
            f"{self._system_prompt}\n\n"
            "Normalize each descriptor below. Return ONLY a JSON object of the "
            'form {"results": [{"idx": <int>, "channel": <str>, '
            '"normalized_name": <str>, "display_name": <str>, '
            '"counterparty": <str|null>}]} with exactly one entry per input idx.'
            "\n\nDescriptors (idx<TAB>descriptor):\n"
            f"{numbered}\n"
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    # -- provider plumbing --------------------------------------------------

    async def _call_llm(self, prompt: str) -> str:
        if self._provider == "gemini":
            return await self._call_gemini(prompt)
        return await self._call_openai(prompt)

    async def _call_openai(self, prompt: str) -> str:
        if self._openai_client is None:
            from openai import AsyncOpenAI

            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is required to call OpenAI.")
            self._openai_client = AsyncOpenAI(api_key=api_key)

        async with self._semaphore:
            with observability.llm_generation(
                f"normalize:{self._model}", model=self._model, input=prompt
            ) as gen:
                resp = await self._openai_client.responses.create(  # type: ignore[attr-defined]
                    model=self._model,
                    input=prompt,
                )
                text = getattr(resp, "output_text", None) or str(resp)
                gen.update(output=text)
                return text

    async def _call_gemini(self, prompt: str) -> str:
        if self._gemini_client is None:
            from google.genai.client import Client

            api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY is required to call Gemini.")
            self._gemini_client = Client(api_key=api_key)

        from google.genai.types import GenerateContentConfig

        config = GenerateContentConfig(response_mime_type="application/json")
        async with self._semaphore:
            with observability.llm_generation(
                f"normalize:{self._model}", model=self._model, input=prompt
            ) as gen:
                resp = await self._gemini_client.aio.models.generate_content(  # type: ignore[attr-defined]
                    model=self._model, contents=prompt, config=config
                )
                text = getattr(resp, "text", None) or str(resp)
                gen.update(output=text)
                return text
