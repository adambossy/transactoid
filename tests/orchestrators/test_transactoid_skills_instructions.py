"""Tests for skill instruction injection in Transactoid orchestrator."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.skills.paths import resolve_skill_paths
from transactoid.core.runtime.skills.prompting import generate_skill_instructions
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.core import Taxonomy


@pytest.fixture(autouse=True)
def _set_openai_api_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_skill_instructions_injected_when_paths_exist(tmp_path: Path) -> None:
    """Test that skill instructions are generated when skill paths exist."""
    # Setup - create skill directory
    project_skills = tmp_path / ".claude" / "skills"
    project_skills.mkdir(parents=True)

    # Act - resolve paths and generate instructions
    paths = resolve_skill_paths(
        project_dir=str(project_skills),
        user_dir="/nonexistent/user",
        builtin_dir="/nonexistent/builtin",
    )
    instructions = generate_skill_instructions(paths)

    # Assert - instructions were generated
    assert instructions != ""
    assert "Agent Skills" in instructions
    assert str(project_skills) in instructions


def test_create_runtime_without_skill_directories() -> None:
    """Test that create_runtime works when no skill directories exist."""
    # Setup
    db = MagicMock()
    db.compact_schema_hint.return_value = {"tables": []}
    taxonomy = Taxonomy([])

    orchestrator = Transactoid(db=db, taxonomy=taxonomy)

    # Create runtime config with nonexistent paths
    config = CoreRuntimeConfig(
        provider="openai",
        model="gpt-5.3",
        skills_project_dir="/nonexistent/project",
        skills_user_dir="/nonexistent/user",
        skills_builtin_dir="/nonexistent/builtin",
    )

    # Act
    runtime = orchestrator.create_runtime(runtime_config=config)

    # Assert - runtime was created successfully even without skill dirs
    assert runtime is not None


def test_create_runtime_skips_custom_skill_instructions_for_langgraph(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_project_skills = tmp_path / ".claude" / "skills"
    input_project_skills.mkdir(parents=True)
    input_config = CoreRuntimeConfig(
        provider="langgraph",
        model="google_genai:gemini-3-flash-preview",
        skills_project_dir=str(input_project_skills),
        skills_user_dir="/nonexistent/user",
        skills_builtin_dir="/nonexistent/builtin",
    )

    # helper setup
    input_db = MagicMock()
    input_db.compact_schema_hint.return_value = {"tables": []}
    input_taxonomy = Taxonomy([])
    unit = Transactoid(db=input_db, taxonomy=input_taxonomy)
    captured_instructions: dict[str, str] = {}

    def create_runtime_stub(
        *,
        config: CoreRuntimeConfig,
        instructions: str,
        registry: object,
    ) -> object:
        _ = config, registry
        captured_instructions["value"] = instructions
        return object()

    monkeypatch.setattr(
        "transactoid.orchestrators.transactoid._render_prompt_template",
        lambda *args, **kwargs: "BASE_INSTRUCTIONS",
    )
    monkeypatch.setattr(
        "transactoid.orchestrators.transactoid.create_core_runtime",
        create_runtime_stub,
    )
    monkeypatch.setattr(
        Transactoid,
        "_build_tool_registry",
        lambda self: MagicMock(),
    )

    # act
    output = unit.create_runtime(runtime_config=input_config)

    # expected
    expected_output = "BASE_INSTRUCTIONS"

    # assert
    assert output is not None and captured_instructions["value"] == expected_output


def test_create_runtime_includes_custom_skill_instructions_for_openai(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # input
    input_project_skills = tmp_path / ".claude" / "skills"
    input_project_skills.mkdir(parents=True)
    input_config = CoreRuntimeConfig(
        provider="openai",
        model="gpt-5.3",
        skills_project_dir=str(input_project_skills),
        skills_user_dir="/nonexistent/user",
        skills_builtin_dir="/nonexistent/builtin",
    )

    # helper setup
    input_db = MagicMock()
    input_db.compact_schema_hint.return_value = {"tables": []}
    input_taxonomy = Taxonomy([])
    unit = Transactoid(db=input_db, taxonomy=input_taxonomy)
    captured_instructions: dict[str, str] = {}

    def create_runtime_stub(
        *,
        config: CoreRuntimeConfig,
        instructions: str,
        registry: object,
    ) -> object:
        _ = config, registry
        captured_instructions["value"] = instructions
        return object()

    monkeypatch.setattr(
        "transactoid.orchestrators.transactoid._render_prompt_template",
        lambda *args, **kwargs: "BASE_INSTRUCTIONS",
    )
    monkeypatch.setattr(
        "transactoid.orchestrators.transactoid.create_core_runtime",
        create_runtime_stub,
    )
    monkeypatch.setattr(
        Transactoid,
        "_build_tool_registry",
        lambda self: MagicMock(),
    )

    # act
    output = unit.create_runtime(runtime_config=input_config)

    # expected
    expected_output = captured_instructions["value"]

    # assert
    assert output is not None and "Agent Skills" in expected_output
