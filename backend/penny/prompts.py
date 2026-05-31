"""Load prompts from the ``backend/prompts/`` directory at runtime.

The system prompt + all historical prompts live as plain markdown files
on disk so they're easy to edit without touching code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the contents of ``prompts/<name>.md``.

    Raises ``FileNotFoundError`` if the file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
