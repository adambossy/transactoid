from __future__ import annotations

import os
from pathlib import Path
import threading

from loguru import logger

from transactoid.memory.index_generation import (
    DEFAULT_MEMORY_INDEX_MODEL,
    DEFAULT_MEMORY_INDEX_PROMPT_KEY,
    MemoryIndexSyncResult,
    sync_memory_index,
)

_initialized_roots: set[Path] = set()
_init_lock = threading.Lock()


def run_initialization_hooks(
    *,
    memory_dir: Path = Path("memory"),
) -> tuple[bool, MemoryIndexSyncResult | None, str | None]:
    """Run one-time initialization hooks for agent startup.

    This hook is intentionally best-effort. Failures are logged and surfaced in
    the returned result, but callers should continue startup.
    """
    resolved_memory_dir = memory_dir.resolve()

    with _init_lock:
        if resolved_memory_dir in _initialized_roots:
            return (False, None, None)

    model = (
        os.environ.get(
            "TRANSACTOID_MEMORY_INDEX_MODEL", DEFAULT_MEMORY_INDEX_MODEL
        ).strip()
        or DEFAULT_MEMORY_INDEX_MODEL
    )
    prompt_key = (
        os.environ.get(
            "TRANSACTOID_MEMORY_INDEX_PROMPT_KEY", DEFAULT_MEMORY_INDEX_PROMPT_KEY
        ).strip()
        or DEFAULT_MEMORY_INDEX_PROMPT_KEY
    )

    try:
        sync_result = sync_memory_index(
            memory_dir=resolved_memory_dir,
            model=model,
            prompt_key=prompt_key,
        )
        logger.bind(
            memory_dir=str(resolved_memory_dir),
            updated=sync_result.updated,
            model=sync_result.model,
        ).info("Memory index sync completed: {}", sync_result.reason)
    except Exception as e:
        logger.bind(memory_dir=str(resolved_memory_dir)).warning(
            "Memory index sync failed during initialization: {}", e
        )
        return (False, None, str(e))

    with _init_lock:
        _initialized_roots.add(resolved_memory_dir)

    return (True, sync_result, None)
