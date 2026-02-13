"""Tests for filesystem policy enforcement."""

from pathlib import Path

from transactoid.core.runtime.skills.policy import (
    is_command_allowed,
    is_path_in_scope,
)


def test_is_command_allowed_read_commands() -> None:
    """Test that read-only commands are allowed."""
    # Input - allowed commands
    allowed_commands = [
        "ls -la",
        "cat file.txt",
        "grep pattern file.txt",
        "find . -name '*.md'",
        "pwd",
        "head -n 10 file.txt",
        "tail -f log.txt",
        "rg --files",
        "sed -n '1,10p' file.txt",
    ]

    # Act & Assert
    for command in allowed_commands:
        assert is_command_allowed(command), f"Command should be allowed: {command}"


def test_is_command_allowed_mutating_commands() -> None:
    """Test that mutating commands are blocked."""
    # Input - denied commands
    denied_commands = [
        "rm file.txt",
        "mv old.txt new.txt",
        "cp file.txt backup.txt",
        "mkdir newdir",
        "rmdir olddir",
        "chmod 755 file.txt",
        "touch newfile.txt",
        "pip install package",
        "npm install",
        "apt install vim",
    ]

    # Act & Assert
    for command in denied_commands:
        assert not is_command_allowed(command), f"Command should be blocked: {command}"


def test_is_command_allowed_redirection_blocked() -> None:
    """Test that redirection operators are blocked."""
    # Input - commands with redirection
    redirection_commands = [
        "cat file.txt > output.txt",
        "echo 'text' >> file.txt",
        "sed 's/old/new/' < input.txt > output.txt",
        "grep pattern file.txt > results.txt",
    ]

    # Act & Assert
    for command in redirection_commands:
        assert not is_command_allowed(command), (
            f"Redirection should be blocked: {command}"
        )


def test_is_command_allowed_empty_command() -> None:
    """Test that empty command is blocked."""
    # Act
    result = is_command_allowed("")

    # Assert
    assert not result


def test_is_command_allowed_unknown_command() -> None:
    """Test that unknown commands are blocked."""
    # Input
    command = "unknown_command arg1 arg2"

    # Act
    result = is_command_allowed(command)

    # Assert
    assert not result


def test_is_path_in_scope_within_allowed_root(tmp_path: Path) -> None:
    """Test that paths within allowed roots are in scope."""
    # Setup
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    test_file = skill_dir / "test.md"
    test_file.touch()

    allowed_roots = [skill_dir]

    # Act
    result = is_path_in_scope(test_file, allowed_roots)

    # Assert
    assert result


def test_is_path_in_scope_outside_allowed_root(tmp_path: Path) -> None:
    """Test that paths outside allowed roots are out of scope."""
    # Setup
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.touch()

    allowed_roots = [skill_dir]

    # Act
    result = is_path_in_scope(outside_file, allowed_roots)

    # Assert
    assert not result


def test_is_path_in_scope_exact_root_match(tmp_path: Path) -> None:
    """Test that the root path itself is in scope."""
    # Setup
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    allowed_roots = [skill_dir]

    # Act
    result = is_path_in_scope(skill_dir, allowed_roots)

    # Assert
    assert result


def test_is_path_in_scope_no_allowed_roots(tmp_path: Path) -> None:
    """Test that paths are out of scope when no allowed roots exist."""
    # Setup
    test_file = tmp_path / "test.txt"
    test_file.touch()

    allowed_roots: list[Path] = []

    # Act
    result = is_path_in_scope(test_file, allowed_roots)

    # Assert
    assert not result


def test_is_path_in_scope_multiple_allowed_roots(tmp_path: Path) -> None:
    """Test path checking with multiple allowed roots."""
    # Setup
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()

    file_in_root1 = root1 / "file.txt"
    file_in_root2 = root2 / "file.txt"
    file_outside = tmp_path / "outside.txt"

    file_in_root1.touch()
    file_in_root2.touch()
    file_outside.touch()

    allowed_roots = [root1, root2]

    # Act & Assert
    assert is_path_in_scope(file_in_root1, allowed_roots)
    assert is_path_in_scope(file_in_root2, allowed_roots)
    assert not is_path_in_scope(file_outside, allowed_roots)


def test_is_path_in_scope_nested_paths(tmp_path: Path) -> None:
    """Test path checking with nested directory structures."""
    # Setup
    skill_dir = tmp_path / "skills"
    nested_dir = skill_dir / "category" / "subcategory"
    nested_dir.mkdir(parents=True)
    nested_file = nested_dir / "skill.md"
    nested_file.touch()

    allowed_roots = [skill_dir]

    # Act
    result = is_path_in_scope(nested_file, allowed_roots)

    # Assert
    assert result
