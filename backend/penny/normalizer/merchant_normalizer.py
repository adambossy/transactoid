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
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
import yaml

from penny.config import load_runtime_config_from_env
from penny.llm import LLMClient, Provider, infer_provider
from penny.normalizer.core import KNOWN_CHANNELS, NormalizedMerchant, naive_normalize

_RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True, slots=True)
class ChannelRule:
    channel: str
    detect: str
    extract: str
    normalized_name: str
    display_name: str
    counterparty: str | None
    examples: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: int
    default_channel: str
    channels: tuple[ChannelRule, ...]

    @property
    def channel_names(self) -> list[str]:
        return [c.channel for c in self.channels]


@lru_cache(maxsize=1)
def load_rules() -> RuleSet:
    """Load and cache ``rules.yaml`` from the package directory."""
    data = yaml.safe_load(_RULES_PATH.read_text())
    channels = tuple(
        ChannelRule(
            channel=str(c["channel"]),
            detect=str(c["detect"]).strip(),
            extract=str(c["extract"]).strip(),
            normalized_name=str(c["normalized_name"]).strip(),
            display_name=str(c["display_name"]).strip(),
            counterparty=(
                None if c.get("counterparty") is None else str(c["counterparty"])
            ),
            examples=list(c.get("examples", [])),
        )
        for c in data["channels"]
    )
    return RuleSet(
        version=int(data["version"]),
        default_channel=str(data.get("default_channel", "direct")),
        channels=channels,
    )


def build_system_prompt(rules: RuleSet) -> str:
    """Render the rule repository into an instruction prompt for the LLM."""
    lines: list[str] = [
        "You normalize raw bank transaction descriptors into stable merchant",
        "identities. A descriptor may be a 'wrapper' (Zelle, ATM, bill pay, ACH,",
        "etc.) that hides the real counterparty behind boilerplate and",
        "per-transaction noise, or it may be an ordinary 'direct' merchant.",
        "",
        "For each descriptor decide which channel it belongs to, then extract its",
        "identity per that channel's rule. The goal: two transactions with the",
        "same real counterparty must get the SAME normalized_name, and distinct",
        "counterparties must get DIFFERENT normalized_names. Strip per-transaction",
        "noise (confirmation hashes, ids, dates, masked account numbers).",
        "",
        f"Known channels (default is '{rules.default_channel}'):",
        "",
    ]
    for c in rules.channels:
        lines.append(f"## channel: {c.channel}")
        lines.append(f"- detect: {c.detect}")
        lines.append(f"- extract: {c.extract}")
        lines.append(f"- normalized_name: {c.normalized_name}")
        lines.append(f"- display_name: {c.display_name}")
        for ex in c.examples:
            lines.append(
                f"- example: {ex.get('descriptor')!r} -> "
                f"normalized_name={ex.get('normalized_name')!r}, "
                f"counterparty={ex.get('counterparty')!r}"
            )
        lines.append("")
    lines += [
        "If a descriptor matches no wrapper channel, classify it as",
        f"'{rules.default_channel}' with counterparty=null; its normalized_name",
        "will be computed deterministically by the caller, so you may return the",
        "descriptor itself as normalized_name for direct merchants.",
        "",
        "normalized_name must be a lowercase slug (letters, digits, hyphens).",
    ]
    return "\n".join(lines)


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


class MerchantNormalizer:
    """Normalize descriptors into :class:`NormalizedMerchant` via an LLM."""

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        model: str | None = None,
        batch_size: int = 40,
    ) -> None:
        resolved_provider, self._model = self._resolve(provider, model)
        self._batch_size = batch_size
        self._system_prompt = build_system_prompt(load_rules())
        self._client = LLMClient(provider=resolved_provider, model=self._model)

    @property
    def model(self) -> str:
        return self._model

    def _resolve(
        self, provider: Provider | None, model: str | None
    ) -> tuple[Provider, str]:
        norm_model = os.environ.get("PENNY_NORMALIZER_MODEL", "").strip() or None
        cat_model = os.environ.get("PENNY_CATEGORIZER_MODEL", "").strip() or None
        chosen = model or norm_model or cat_model
        inferred = infer_provider(chosen)
        try:
            runtime = load_runtime_config_from_env()
            resolved_model = chosen or runtime.model
        except Exception:
            resolved_model = chosen or "gpt-5.5"
        resolved_provider = (
            provider or inferred or infer_provider(resolved_model) or "openai"
        )
        if resolved_provider not in ("openai", "gemini"):
            resolved_provider = "openai"
        return resolved_provider, resolved_model

    # -- public API ---------------------------------------------------------

    async def normalize(self, descriptor: str) -> NormalizedMerchant:
        result = await self.normalize_many([descriptor])
        # Missing => the batch failed; fall back to the naive key so this
        # convenience method stays total.
        return result.get(descriptor) or naive_normalize(descriptor)

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
            raw = await self._client.complete(
                prompt, trace_name="normalize", json_mode=True
            )
            parsed = _ExtractionResponse.model_validate_json(self._extract_json(raw))
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            # Omit the batch rather than fabricate identities. Callers treat a
            # missing descriptor as unresolved: the sync path falls back to the
            # facade's merchant_descriptor-based naive resolution, which is a
            # clean collapsed identity (e.g. "venmo") — never junk derived from
            # the raw wrapper text (which would strand the row on a bad merchant).
            logger.warning("normalizer LLM batch failed ({}); leaving unresolved", exc)
            return {}

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
