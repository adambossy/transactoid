from __future__ import annotations

from pathlib import Path
from typing import Any

from transactoid.memory import index_generation
from transactoid.memory.index_generation import MemoryIndexSyncResult, sync_memory_index


def test_runtime_tax_return_files_excludes_example_files(tmp_path: Path) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()
    input_tax_dir = input_memory_dir / "tax-returns"
    input_tax_dir.mkdir()
    (input_tax_dir / "2024.pdf").write_text("2024")
    (input_tax_dir / "2026.md.example").write_text("example")

    # act
    output = index_generation._runtime_tax_return_files(memory_dir=input_memory_dir)

    # expected
    expected_output = ["tax-returns/2024.pdf"]

    # assert
    assert output == expected_output


def test_build_memory_tree_excludes_example_files(tmp_path: Path) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()
    input_tax_dir = input_memory_dir / "tax-returns"
    input_tax_dir.mkdir()
    (input_tax_dir / "2024.pdf").write_text("2024")
    (input_tax_dir / "2026.md.example").write_text("example")

    # act
    output = index_generation._build_memory_tree(memory_dir=input_memory_dir)

    # expected
    expected_output = "2024.pdf"

    # assert
    assert expected_output in output
    assert "2026.md.example" not in output


def test_sync_memory_index_skips_write_when_content_is_unchanged(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()
    input_index_path = input_memory_dir / "index.md"
    input_index_text = "# Memory Index\n\n## Annotations\n\n## Tax Returns Directory\n"
    input_index_path.write_text(input_index_text)

    # helper setup
    def create_generated_index(**_: object) -> str:
        return input_index_text

    monkeypatch.setattr(
        index_generation,
        "generate_memory_index_markdown",
        create_generated_index,
    )

    # act
    output = sync_memory_index(memory_dir=input_memory_dir)

    # expected
    expected_output = MemoryIndexSyncResult(
        updated=False,
        path=input_index_path,
        model="gemini-3-pro-preview",
        reason="content unchanged",
    )

    # assert
    assert output == expected_output


def test_sync_memory_index_writes_when_content_changes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_memory_dir = tmp_path / "memory"
    input_memory_dir.mkdir()
    input_index_path = input_memory_dir / "index.md"
    input_index_path.write_text("old")
    input_generated = "# Memory Index\n\n## Annotations\n\n## Tax Returns Directory\n"

    # helper setup
    def create_generated_index(**_: object) -> str:
        return input_generated

    monkeypatch.setattr(
        index_generation,
        "generate_memory_index_markdown",
        create_generated_index,
    )

    # act
    output = sync_memory_index(memory_dir=input_memory_dir)

    # expected
    expected_output = MemoryIndexSyncResult(
        updated=True,
        path=input_index_path,
        model="gemini-3-pro-preview",
        reason="content changed",
    )

    # assert
    assert output == expected_output
