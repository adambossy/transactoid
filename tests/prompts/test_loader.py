from __future__ import annotations

from typing import Any

import pytest

from transactoid.prompts.loader import PromptLoadError, load_transactoid_prompt


def test_load_transactoid_prompt_uses_bundled_fallback_when_promptorium_fails(
    monkeypatch: Any,
) -> None:
    # input
    input_prompt_key = "agent-loop"

    # helper setup
    def raise_runtime_error(prompt_key: str) -> str:
        raise RuntimeError(prompt_key)

    monkeypatch.setattr(
        "transactoid.prompts.loader.promptorium_load_prompt",
        raise_runtime_error,
    )

    # act
    output = load_transactoid_prompt(input_prompt_key)

    # expected
    expected_substring = "Transactoid"

    # assert
    assert expected_substring in output


def test_load_transactoid_prompt_raises_when_prompt_missing(
    monkeypatch: Any,
) -> None:
    # input
    input_prompt_key = "missing-prompt-key"

    # helper setup
    def raise_runtime_error(prompt_key: str) -> str:
        raise RuntimeError(prompt_key)

    monkeypatch.setattr(
        "transactoid.prompts.loader.promptorium_load_prompt",
        raise_runtime_error,
    )

    # act + assert
    with pytest.raises(PromptLoadError, match=input_prompt_key):
        load_transactoid_prompt(input_prompt_key)
