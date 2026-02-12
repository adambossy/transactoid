"""Tests for skill path resolution."""

from pathlib import Path

from transactoid.core.runtime.skills.paths import (
    ResolvedSkillPaths,
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
