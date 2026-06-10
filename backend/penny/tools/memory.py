"""Memory tools — regenerate the memory index the agent reads each turn.

``memory/index.md`` is injected into every system prompt (via
``{{AGENT_MEMORY}}``), so it must be refreshed whenever memory files are
added, removed, or restructured. The startup auto-indexer from the original
codebase was deliberately dropped; this tool is the agent-invocable
replacement.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_harness import tool

from penny.memory.index_generation import sync_memory_index
from penny.workspace import resolve_memory_dir


@tool
async def generate_memory_index(force: bool = False) -> dict[str, Any]:
    """Regenerate ``memory/index.md`` from the current memory directory.

    Call this after adding, removing, or restructuring files under the
    workspace ``memory/`` directory so the index (which is loaded into
    your own context every turn) stays accurate.

    Args:
        force: Rewrite even if the generated content is unchanged.
    """

    def _run() -> dict[str, Any]:
        try:
            result = sync_memory_index(memory_dir=resolve_memory_dir(), force=force)
            return {
                "status": "success",
                "updated": result.updated,
                "path": str(result.path),
                "model": result.model,
                "reason": result.reason,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    return await asyncio.to_thread(_run)
