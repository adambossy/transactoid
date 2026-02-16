from __future__ import annotations

from pathlib import Path

from transactoid.orchestrators.transactoid import _assemble_agent_memory


def test_assemble_agent_memory_includes_only_core_files(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    (memory_dir / "index.md").write_text("# Index\n\nMemory index content")
    (memory_dir / "merchant-rules.md").write_text("# Merchant Rules\n\nRules content")
    (memory_dir / "budget.md").write_text("# Budget\n\nOptional budget content")
    tax_returns_dir = memory_dir / "tax-returns"
    tax_returns_dir.mkdir()
    (tax_returns_dir / "2024.md").write_text("# Tax Return\n\nSensitive content")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert "# Index" in result
    assert "# Merchant Rules" in result
    assert "# Budget" not in result
    assert "Sensitive content" not in result


def test_assemble_agent_memory_with_index_only_returns_index(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Index\n\nMemory index")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == "# Index\n\nMemory index"


def test_assemble_agent_memory_with_no_core_files_returns_empty(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "budget.md").write_text("# Budget")
    tax_returns_dir = memory_dir / "tax-returns"
    tax_returns_dir.mkdir()
    (tax_returns_dir / "2024.md").write_text("Return content")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == ""


def test_assemble_agent_memory_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "nonexistent"

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == ""


def test_assemble_agent_memory_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert result == ""


def test_assemble_agent_memory_appends_runtime_tax_returns_inventory(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Index")
    tax_returns_dir = memory_dir / "tax-returns"
    tax_returns_dir.mkdir()
    (tax_returns_dir / "2023.md").write_text("2023 data")
    (tax_returns_dir / "w2.pdf").write_text("w2 data")
    (tax_returns_dir / "2026.md.example").write_text("example content")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    assert "## Local Tax Return Files (Runtime)" in result
    assert "`memory/tax-returns/2023.md`" not in result
    assert "`tax-returns/2023.md`" in result
    assert "`tax-returns/w2.pdf`" in result
    assert "2023 data" not in result
    assert "example content" not in result


def test_assemble_agent_memory_inventory_is_sorted(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Index")
    tax_returns_dir = memory_dir / "tax-returns"
    nested_dir = tax_returns_dir / "raw"
    nested_dir.mkdir(parents=True)
    (tax_returns_dir / "z-file.txt").write_text("z")
    (nested_dir / "a-file.txt").write_text("a")

    result = _assemble_agent_memory(memory_dir=memory_dir)

    a_pos = result.find("`tax-returns/raw/a-file.txt`")
    z_pos = result.find("`tax-returns/z-file.txt`")

    assert a_pos < z_pos
