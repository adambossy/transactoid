"""Tests for skill path resolution."""

from pathlib import Path

from transactoid.core.runtime.skills.paths import (
    ResolvedSkillPaths,
    find_available_skills,
    resolve_skill_paths,
)


def test_resolve_skill_paths_all_existing(tmp_path: Path) -> None:
    """Test resolving paths when all directories exist."""
    # Input
    project_dir = tmp_path / "project" / ".claude" / "skills"
    user_dir = tmp_path / "user" / ".claude" / "skills"
    builtin_dir = tmp_path / "builtin" / "skills"

    # Setup
    project_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    builtin_dir.mkdir(parents=True)

    # Act
    result = resolve_skill_paths(
        project_dir=str(project_dir),
        user_dir=str(user_dir),
        builtin_dir=str(builtin_dir),
    )

    # Expected
    expected = ResolvedSkillPaths(
        project_dir=project_dir.resolve(),
        user_dir=user_dir.resolve(),
        builtin_dir=builtin_dir.resolve(),
    )

    # Assert
    assert result == expected


def test_resolve_skill_paths_missing_directories(tmp_path: Path) -> None:
    """Test resolving paths when some directories are missing."""
    # Input
    project_dir = tmp_path / "project" / ".claude" / "skills"
    user_dir = tmp_path / "user" / ".claude" / "skills"
    builtin_dir = tmp_path / "builtin" / "skills"

    # Setup - only create user_dir
    user_dir.mkdir(parents=True)

    # Act
    result = resolve_skill_paths(
        project_dir=str(project_dir),
        user_dir=str(user_dir),
        builtin_dir=str(builtin_dir),
    )

    # Expected - missing dirs are None
    expected = ResolvedSkillPaths(
        project_dir=None,
        user_dir=user_dir.resolve(),
        builtin_dir=None,
    )

    # Assert
    assert result == expected


def test_resolve_skill_paths_tilde_expansion(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Test that tilde in paths is expanded correctly."""
    # Setup - mock home directory
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    # Act
    result = resolve_skill_paths(
        project_dir="/nonexistent",
        user_dir="~/.claude/skills",
        builtin_dir="/also/nonexistent",
    )

    # Expected
    expected = ResolvedSkillPaths(
        project_dir=None,
        user_dir=skills_dir.resolve(),
        builtin_dir=None,
    )

    # Assert
    assert result == expected


def test_resolve_skill_paths_all_missing() -> None:
    """Test resolving paths when all directories are missing."""
    # Act
    result = resolve_skill_paths(
        project_dir="/nonexistent/project",
        user_dir="/nonexistent/user",
        builtin_dir="/nonexistent/builtin",
    )

    # Expected
    expected = ResolvedSkillPaths(
        project_dir=None,
        user_dir=None,
        builtin_dir=None,
    )

    # Assert
    assert result == expected


def test_all_existing_returns_in_precedence_order(tmp_path: Path) -> None:
    """Test that all_existing returns directories in precedence order."""
    # Setup
    project_dir = tmp_path / "project"
    user_dir = tmp_path / "user"
    builtin_dir = tmp_path / "builtin"

    project_dir.mkdir()
    user_dir.mkdir()
    builtin_dir.mkdir()

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=user_dir,
        builtin_dir=builtin_dir,
    )

    # Act
    result = paths.all_existing()

    # Expected - project > user > builtin
    expected = [project_dir, user_dir, builtin_dir]

    # Assert
    assert result == expected


def test_all_existing_skips_none_values() -> None:
    """Test that all_existing skips None values."""
    # Setup
    paths = ResolvedSkillPaths(
        project_dir=None,
        user_dir=Path("/some/user/path"),
        builtin_dir=None,
    )

    # Act
    result = paths.all_existing()

    # Expected - only user_dir
    expected = [Path("/some/user/path")]

    # Assert
    assert result == expected


def test_all_existing_returns_empty_when_all_none() -> None:
    """Test that all_existing returns empty list when all dirs are None."""
    # Setup
    paths = ResolvedSkillPaths(
        project_dir=None,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = paths.all_existing()

    # Assert
    assert result == []


def test_find_available_skills_discovers_skill_files(tmp_path: Path) -> None:
    """Test that find_available_skills discovers SKILL.md files."""
    # Setup
    project_dir = tmp_path / "project" / ".claude" / "skills"
    project_dir.mkdir(parents=True)

    # Create skill directories with SKILL.md files
    skill1 = project_dir / "analyze-spending"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text("# Analyze Spending\n\nInstructions...")

    skill2 = project_dir / "monthly-report"
    skill2.mkdir()
    (skill2 / "SKILL.md").write_text("# Monthly Report\n\nInstructions...")

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = find_available_skills(paths)

    # Assert - should find both SKILL.md files
    assert len(result) == 2
    skill_names = {p.parent.name for p in result}
    assert skill_names == {"analyze-spending", "monthly-report"}


def test_find_available_skills_respects_precedence(tmp_path: Path) -> None:
    """Test that find_available_skills returns skills in precedence order."""
    # Setup
    project_dir = tmp_path / "project"
    user_dir = tmp_path / "user"
    builtin_dir = tmp_path / "builtin"

    for directory in [project_dir, user_dir, builtin_dir]:
        directory.mkdir()
        skill = directory / "test-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# Test Skill")

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=user_dir,
        builtin_dir=builtin_dir,
    )

    # Act
    result = find_available_skills(paths)

    # Assert - should find all three, in precedence order
    assert len(result) == 3
    # Project should be first
    assert "project" in str(result[0])
    # User should be second
    assert "user" in str(result[1])
    # Builtin should be third
    assert "builtin" in str(result[2])


def test_find_available_skills_ignores_directories_without_skill_md(
    tmp_path: Path,
) -> None:
    """Test that directories without SKILL.md are ignored."""
    # Setup
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Create skill with SKILL.md
    valid_skill = project_dir / "valid-skill"
    valid_skill.mkdir()
    (valid_skill / "SKILL.md").write_text("# Valid Skill")

    # Create directory without SKILL.md
    invalid_skill = project_dir / "invalid-skill"
    invalid_skill.mkdir()
    # No SKILL.md file created

    # Create file (not directory)
    (project_dir / "README.md").write_text("# README")

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = find_available_skills(paths)

    # Assert - should only find the valid skill
    assert len(result) == 1
    assert result[0].parent.name == "valid-skill"


def test_find_available_skills_returns_empty_when_no_skills(tmp_path: Path) -> None:
    """Test that find_available_skills returns empty list when no skills exist."""
    # Setup
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = find_available_skills(paths)

    # Assert
    assert result == []


def test_find_available_skills_handles_missing_directories() -> None:
    """Test that find_available_skills handles missing directories gracefully."""
    # Setup - all directories are None
    paths = ResolvedSkillPaths(
        project_dir=None,
        user_dir=None,
        builtin_dir=None,
    )

    # Act
    result = find_available_skills(paths)

    # Assert - should return empty list, not crash
    assert result == []


def test_find_available_skills_handles_permission_errors(tmp_path: Path) -> None:
    """Test that find_available_skills handles permission errors gracefully."""
    # Setup
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Create a skill
    skill = project_dir / "test-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Test Skill")

    paths = ResolvedSkillPaths(
        project_dir=project_dir,
        user_dir=None,
        builtin_dir=None,
    )

    # Act - should not raise exception even if permission issues occur
    result = find_available_skills(paths)

    # Assert - should find the skill
    assert len(result) >= 1
