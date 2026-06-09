"""Single prompt loader for the whole backend.

Source of truth: ``backend/.prompts/<key>/<version>.md`` (promptorium's
managed-by-root layout). The index lives at ``.prompts/_meta.json``.

Every consumer — ``agent_factory`` (system prompt), the categorizer
(categorize-transactions, taxonomy-rules), reports, etc. — reads through
this single function so there's exactly one prompt directory and one
loader semantics.
"""

from __future__ import annotations

from functools import lru_cache

from promptorium import load_prompt as _promptorium_load_prompt


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the latest version of the named prompt.

    Backed by promptorium; raises ``promptorium.domain.PromptNotFound`` (or
    similar) if the key is missing. Cached per-process.
    """
    return _promptorium_load_prompt(name)
