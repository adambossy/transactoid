from __future__ import annotations

from transactoid.core.runtime.claude_runtime import ClaudeCoreRuntime
from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.gemini_runtime import GeminiCoreRuntime
from transactoid.core.runtime.openai_runtime import OpenAICoreRuntime
from transactoid.core.runtime.protocol import CoreRuntime
from transactoid.tools.registry import ToolRegistry


def create_core_runtime(
    *,
    config: CoreRuntimeConfig,
    instructions: str,
    registry: ToolRegistry,
) -> CoreRuntime:
    """Create a provider-specific runtime from startup config."""
    if config.provider == "openai":
        return OpenAICoreRuntime(
            instructions=instructions,
            registry=registry,
            config=config,
        )

    if config.provider == "claude":
        return ClaudeCoreRuntime(
            instructions=instructions,
            registry=registry,
            config=config,
        )

    if config.provider == "gemini":
        return GeminiCoreRuntime(
            instructions=instructions,
            registry=registry,
            config=config,
        )

    raise ValueError(f"Unknown runtime provider: {config.provider}")
