from __future__ import annotations

from typing import Any

from transactoid.core.runtime.config import load_core_runtime_config_from_env


def test_load_core_runtime_config_normalizes_langgraph_gemini_model(
    monkeypatch: Any,
) -> None:
    # input
    input_provider = "langgraph"
    input_model = "gemini-3-pro-preview"

    # helper setup
    monkeypatch.setenv("TRANSACTOID_AGENT_PROVIDER", input_provider)
    monkeypatch.setenv("TRANSACTOID_AGENT_MODEL", input_model)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

    # act
    output = load_core_runtime_config_from_env()

    # expected
    expected_output = "google_genai:gemini-3-pro-preview"

    # assert
    assert output.model == expected_output


def test_load_core_runtime_config_preserves_langgraph_prefixed_model(
    monkeypatch: Any,
) -> None:
    # input
    input_provider = "langgraph"
    input_model = "openai:gpt-5.3"

    # helper setup
    monkeypatch.setenv("TRANSACTOID_AGENT_PROVIDER", input_provider)
    monkeypatch.setenv("TRANSACTOID_AGENT_MODEL", input_model)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    # act
    output = load_core_runtime_config_from_env()

    # expected
    expected_output = "openai:gpt-5.3"

    # assert
    assert output.model == expected_output
