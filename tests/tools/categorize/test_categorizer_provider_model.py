from __future__ import annotations

from typing import Any, Literal

from transactoid.tools.categorize import categorizer_tool
from transactoid.tools.categorize.categorizer_tool import Categorizer


def test_resolve_provider_model_uses_provider_default_on_env_failure(
    monkeypatch: Any,
) -> None:
    # input
    input_provider: Literal["gemini"] = "gemini"
    input_model = None

    # helper setup
    categorizer = object.__new__(Categorizer)

    def _raise_runtime_config_error() -> object:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(
        categorizer_tool,
        "load_core_runtime_config_from_env",
        _raise_runtime_config_error,
    )
    monkeypatch.delenv("TRANSACTOID_CATEGORIZER_MODEL", raising=False)

    # act
    output = categorizer._resolve_provider_model(
        provider=input_provider,
        model=input_model,
    )

    # expected
    expected_output = ("gemini", "gemini-2.5-pro")

    # assert
    assert output == expected_output


def test_resolve_provider_model_categorizer_env_overrides_agent_model(
    monkeypatch: Any,
) -> None:
    # input: no explicit args; CATEGORIZER env var set to a different model
    input_provider = None
    input_model = None

    # helper setup
    categorizer = object.__new__(Categorizer)

    def _raise_runtime_config_error() -> object:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(
        categorizer_tool,
        "load_core_runtime_config_from_env",
        _raise_runtime_config_error,
    )
    monkeypatch.setenv("TRANSACTOID_CATEGORIZER_MODEL", "gemini-3-pro-preview")

    # act
    output = categorizer._resolve_provider_model(
        provider=input_provider,
        model=input_model,
    )

    # expected: provider falls back to "openai" default; model uses categorizer override
    expected_output = ("openai", "gemini-3-pro-preview")

    # assert
    assert output == expected_output
