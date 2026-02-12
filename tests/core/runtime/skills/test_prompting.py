"""Tests for skill instruction generation."""

from pathlib import Path

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.core.runtime.skills.prompting import generate_skill_instructions


def test_generate_skill_instructions_all_paths() -> None:
    """Test instruction generation when all skill paths exist."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=Path("/project/.claude/skills"),
        user_dir=Path("/home/user/.claude/skills"),
        builtin_dir=Path("/app/src/transactoid/skills"),
    )

    # Act
    result = generate_skill_instructions(paths)

    # Assert - includes all three paths
    assert "/project/.claude/skills" in result
    assert "/home/user/.claude/skills" in result
    assert "/app/src/transactoid/skills" in result
    # Check precedence order is mentioned
    assert "precedence order" in result.lower() or "precedence" in result.lower()
    # Check usage protocol is included
    assert "Discovery" in result or "discovery" in result
    assert "Loading" in result or "loading" in result
    assert "SKILL.md" in result


def test_generate_skill_instructions_partial_paths() -> None:
    """Test instruction generation when only some paths exist."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=None,
        user_dir=Path("/home/user/.claude/skills"),
        builtin_dir=None,
    )

    # Act
    result = generate_skill_instructions(paths)

    # Assert - includes only user path
    assert "/home/user/.claude/skills" in result
    assert "Agent Skills" in result
    assert "Usage Protocol" in result


def test_generate_skill_instructions_no_paths() -> None:
    """Test instruction generation when no paths exist."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=None,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = generate_skill_instructions(paths)

    # Assert - returns empty string
    assert result == ""


def test_generate_skill_instructions_deterministic() -> None:
    """Test that instruction generation is deterministic."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=Path("/project"),
        user_dir=Path("/user"),
        builtin_dir=Path("/builtin"),
    )

    # Act - generate twice
    result1 = generate_skill_instructions(paths)
    result2 = generate_skill_instructions(paths)

    # Assert - results are identical
    assert result1 == result2


def test_generate_skill_instructions_includes_precedence_rules() -> None:
    """Test that instructions include precedence rules."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=Path("/project"),
        user_dir=Path("/user"),
        builtin_dir=Path("/builtin"),
    )

    # Act
    result = generate_skill_instructions(paths)

    # Assert - mentions precedence and overrides
    assert "precedence" in result.lower() or "override" in result.lower()
    assert "project" in result.lower()
    assert "user" in result.lower()
    assert "builtin" in result.lower()


def test_generate_skill_instructions_includes_usage_guidance() -> None:
    """Test that instructions include usage guidance."""
    # Input
    paths = ResolvedSkillPaths(
        project_dir=Path("/project"),
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = generate_skill_instructions(paths)

    # Assert - includes key usage concepts
    assert "filesystem" in result.lower() or "search" in result.lower()
    assert "SKILL.md" in result
    assert "directory" in result.lower() or "directories" in result.lower()
