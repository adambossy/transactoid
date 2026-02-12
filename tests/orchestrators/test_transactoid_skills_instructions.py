"""Tests for skill instruction injection in Transactoid orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock

from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.skills.paths import resolve_skill_paths
from transactoid.core.runtime.skills.prompting import generate_skill_instructions
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.core import Taxonomy


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
