from __future__ import annotations

from pathlib import Path
from typing import Any

from transactoid.orchestrators.transactoid import _render_prompt_template

# --- System Prompt Rendering Tests ---


def test_render_prompt_replaces_agent_memory(tmp_path: Path, monkeypatch: Any) -> None:
    """{{AGENT_MEMORY}} placeholder is replaced with assembled memory."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "index.md").write_text("# Memory Index")
    (memory_dir / "merchant-rules.md").write_text("# Merchant Rules")
    (memory_dir / "budget.md").write_text("# Budget Optional")
    tax_returns_dir = memory_dir / "tax-returns"
    tax_returns_dir.mkdir()
    (tax_returns_dir / "2024.md").write_text("Sensitive tax content")

    import transactoid.orchestrators.transactoid as orchestrator_module

    original_assemble = orchestrator_module._assemble_agent_memory

    def mock_assemble_memory(**kwargs: object) -> str:
        _ = kwargs
        return original_assemble(memory_dir=memory_dir)

    monkeypatch.setattr(
        orchestrator_module, "_assemble_agent_memory", mock_assemble_memory
    )

    template = "Start\n\n{{AGENT_MEMORY}}\n\nEnd"
    database_schema: dict[str, Any] = {}
    category_taxonomy: dict[str, Any] = {"nodes": []}

    result = _render_prompt_template(
        template,
        database_schema=database_schema,
        category_taxonomy=category_taxonomy,
        memory_dir=memory_dir,
    )

    assert "# Memory Index" in result
    assert "# Merchant Rules" in result
    assert "# Budget Optional" not in result
    assert "Sensitive tax content" not in result
    assert "{{AGENT_MEMORY}}" not in result


def test_render_prompt_handles_missing_memory(
    monkeypatch: Any,
) -> None:
    """No crash when memory files are absent."""
    import transactoid.orchestrators.transactoid as orchestrator_module

    def mock_assemble_memory(**kwargs: object) -> str:
        _ = kwargs
        return ""

    monkeypatch.setattr(
        orchestrator_module, "_assemble_agent_memory", mock_assemble_memory
    )

    template = "Start\n\n{{AGENT_MEMORY}}\n\nEnd"
    database_schema: dict[str, Any] = {}
    category_taxonomy: dict[str, Any] = {"nodes": []}

    result = _render_prompt_template(
        template,
        database_schema=database_schema,
        category_taxonomy=category_taxonomy,
        memory_dir=Path("/nonexistent"),
    )

    # Empty memory should result in placeholder being replaced with empty string
    assert "Start\n\n\n\nEnd" in result
    assert "{{AGENT_MEMORY}}" not in result
