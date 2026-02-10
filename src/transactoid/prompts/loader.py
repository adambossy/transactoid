from __future__ import annotations

from pathlib import Path
import re

from promptorium import load_prompt as promptorium_load_prompt


class PromptLoadError(Exception):
    """Raised when a prompt cannot be loaded from any configured source."""


_VERSIONED_PROMPT_PATTERN = re.compile(r"^(?P<key>.+)-(?P<version>\d+)\.md$")


def load_transactoid_prompt(prompt_key: str) -> str:
    """Load a prompt by key via Promptorium, with a bundled-file fallback."""
    promptorium_error: Exception | None = None

    try:
        prompt = promptorium_load_prompt(prompt_key)
        if isinstance(prompt, str):
            return prompt
        raise PromptLoadError(
            f"Prompt {prompt_key!r} did not return text; got {type(prompt).__name__}"
        )
    except Exception as error:  # noqa: BLE001
        promptorium_error = error

    bundled_prompt = _load_latest_bundled_prompt(prompt_key)
    if bundled_prompt is not None:
        return bundled_prompt

    raise PromptLoadError(f"Prompt not found: {prompt_key}") from promptorium_error


def _load_latest_bundled_prompt(prompt_key: str) -> str | None:
    prompt_dir = Path(__file__).resolve().parent / prompt_key
    if not prompt_dir.exists() or not prompt_dir.is_dir():
        return None

    latest_file: Path | None = None
    latest_version = -1

    for path in prompt_dir.glob(f"{prompt_key}-*.md"):
        match = _VERSIONED_PROMPT_PATTERN.match(path.name)
        if not match:
            continue
        version = int(match.group("version"))
        if version > latest_version:
            latest_version = version
            latest_file = path

    if latest_file is None:
        return None
    return latest_file.read_text(encoding="utf-8")
