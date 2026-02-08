from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal

Provider = Literal["openai", "claude", "gemini"]
ReasoningEffort = Literal["low", "medium", "high"]
Verbosity = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class CoreRuntimeConfig:
    """Runtime provider configuration loaded at process startup."""

    provider: Provider
    model: str
    reasoning_effort: ReasoningEffort = "medium"
    verbosity: Verbosity = "high"
    enable_web_search: bool = True


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def load_core_runtime_config_from_env() -> CoreRuntimeConfig:
    """Load runtime config from env and validate startup requirements."""
    provider_value = os.environ.get("TRANSACTOID_AGENT_PROVIDER", "openai").strip()
    if provider_value not in {"openai", "claude", "gemini"}:
        raise ValueError(
            "TRANSACTOID_AGENT_PROVIDER must be one of: openai, claude, gemini"
        )
    provider: Provider = provider_value  # type: ignore[assignment]

    model_default_map = {
        "openai": "gpt-5.3",
        "claude": "",
        "gemini": "",
    }
    default_model = model_default_map[provider]
    model = os.environ.get("TRANSACTOID_AGENT_MODEL", default_model).strip()
    if not model:
        raise ValueError(
            "TRANSACTOID_AGENT_MODEL is required when provider is claude or gemini"
        )

    reasoning_effort = os.environ.get(
        "TRANSACTOID_AGENT_REASONING_EFFORT", "medium"
    ).strip()
    if reasoning_effort not in {"low", "medium", "high"}:
        raise ValueError(
            "TRANSACTOID_AGENT_REASONING_EFFORT must be one of: low, medium, high"
        )

    verbosity = os.environ.get("TRANSACTOID_AGENT_VERBOSITY", "high").strip()
    if verbosity not in {"low", "medium", "high"}:
        raise ValueError(
            "TRANSACTOID_AGENT_VERBOSITY must be one of: low, medium, high"
        )

    enable_web_search = os.environ.get(
        "TRANSACTOID_ENABLE_WEB_SEARCH", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Fail fast on missing provider credentials.
    if provider == "openai":
        _require_env("OPENAI_API_KEY")
    elif provider == "claude":
        _require_env("ANTHROPIC_API_KEY")
    else:
        _require_env("GOOGLE_API_KEY")

    return CoreRuntimeConfig(
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
        verbosity=verbosity,  # type: ignore[arg-type]
        enable_web_search=enable_web_search,
    )
