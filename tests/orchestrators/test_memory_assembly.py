from __future__ import annotations

from pathlib import Path

from transactoid.orchestrators.transactoid import _assemble_agent_memory

# --- Memory Assembly Tests ---


def test_assemble_agent_memory_with_all_files(tmp_path: Path) -> None:
    """Assembled text contains index then other files in sorted order."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    (memory_dir / "index.md").write_text("# Index\n\nMemory index content")
    (memory_dir / "merchant-rules.md").write_text("# Merchant Rules\n\nRules content")
    (memory_dir / "another-file.md").write_text("# Another File\n\nMore content")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert "# Index" in result
    assert "# Merchant Rules" in result
    assert "# Another File" in result
    # Index should come first
    index_pos = result.find("# Index")
    merchant_pos = result.find("# Merchant Rules")
    another_pos = result.find("# Another File")
    assert index_pos < merchant_pos
    # another-file.md comes before merchant-rules.md alphabetically
    assert another_pos < merchant_pos


def test_assemble_agent_memory_with_index_only(tmp_path: Path) -> None:
    """Memory with only index file returns index content."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Index\n\nMemory index")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == "# Index\n\nMemory index"


def test_assemble_agent_memory_with_no_index(tmp_path: Path) -> None:
    """Memory without index returns other files in sorted order."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "rules.md").write_text("# Rules")
    (memory_dir / "config.md").write_text("# Config")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    # config.md comes before rules.md alphabetically
    assert result == "# Config\n\n# Rules"


def test_assemble_agent_memory_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    """Missing memory directory returns empty string."""
    memory_dir = tmp_path / "nonexistent"

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == ""


def test_assemble_agent_memory_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    """Empty memory directory returns empty string."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == ""


def test_assemble_agent_memory_ignores_non_md_files(tmp_path: Path) -> None:
    """Non-markdown files are ignored."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Index")
    (memory_dir / "README.txt").write_text("Text file")
    (memory_dir / "config.json").write_text("{}")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == "# Index"
    assert "Text file" not in result
    assert "{}" not in result


def test_assemble_agent_memory_joins_with_double_newlines(tmp_path: Path) -> None:
    """Files are joined with double newline separator."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "file1.md").write_text("Content 1")
    (memory_dir / "file2.md").write_text("Content 2")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == "Content 1\n\nContent 2"
