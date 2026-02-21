from __future__ import annotations

from pathlib import Path
from typing import Any

import transactoid.bootstrap.initialization as init_module
from transactoid.bootstrap.initialization import run_initialization_hooks
from transactoid.memory.index_generation import MemoryIndexSyncResult


def test_run_initialization_hooks_runs_once_per_memory_dir(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()
    input_sync_result = MemoryIndexSyncResult(
        updated=True,
        path=input_memory_dir / "index.md",
        model="gemini-3-pro-preview",
        reason="content changed",
    )

    # helper setup
    monkeypatch.setattr(init_module, "_initialized_roots", set())

    def create_sync_result(**_: object) -> MemoryIndexSyncResult:
        return input_sync_result

    monkeypatch.setattr(init_module, "sync_memory_index", create_sync_result)

    # act
    output = [
        run_initialization_hooks(memory_dir=input_memory_dir),
        run_initialization_hooks(memory_dir=input_memory_dir),
    ]

    # expected
    expected_output = [
        (True, input_sync_result, None),
        (False, None, None),
    ]

    # assert
    assert output == expected_output


def test_run_initialization_hooks_returns_error_result_on_failure(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()

    # helper setup
    monkeypatch.setattr(init_module, "_initialized_roots", set())

    def raise_sync_error(**_: object) -> MemoryIndexSyncResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(init_module, "sync_memory_index", raise_sync_error)

    # act
    output = run_initialization_hooks(memory_dir=input_memory_dir)

    # expected
    expected_output = (False, None, "boom")

    # assert
    assert output == expected_output
