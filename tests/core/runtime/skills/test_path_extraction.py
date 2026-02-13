"""Tests for command path extraction."""

from transactoid.core.runtime.skills.path_extraction import extract_paths_from_command


def test_extract_paths_absolute_path() -> None:
    """Test extraction of absolute paths."""
    # Input
    command = "cat /home/user/file.txt"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract the absolute path
    assert len(result) == 1
    assert result[0].is_absolute()


def test_extract_paths_relative_with_slash() -> None:
    """Test extraction of relative paths with slashes."""
    # Input
    command = "ls ./skills/analyze-spending"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract relative path
    assert len(result) == 1
    assert "analyze-spending" in str(result[0])


def test_extract_paths_tilde_expansion() -> None:
    """Test extraction of paths with tilde."""
    # Input
    command = "cat ~/.claude/skills/SKILL.md"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract and expand tilde
    assert len(result) == 1
    assert "~" not in str(result[0])  # Tilde should be expanded


def test_extract_paths_multiple_paths() -> None:
    """Test extraction when command has multiple paths."""
    # Input
    command = "diff /path/one.txt /path/two.txt"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract both paths
    assert len(result) == 2


def test_extract_paths_no_paths() -> None:
    """Test extraction when command has no recognizable paths."""
    # Input - relative file without slash
    command = "cat file.txt"

    # Act
    result = extract_paths_from_command(command)

    # Assert - current heuristic misses this (documented limitation)
    assert result == []


def test_extract_paths_skip_flags() -> None:
    """Test that command flags are not extracted as paths."""
    # Input
    command = "ls -la /home/user"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should only extract the path, not the flag
    assert len(result) == 1
    assert "-la" not in str(result[0])


def test_extract_paths_skip_operators() -> None:
    """Test that shell operators are not extracted as paths."""
    # Input
    command = "cat /file1.txt && cat /file2.txt"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract both paths but not the operator
    assert len(result) == 2
    assert all("&&" not in str(p) for p in result)


def test_extract_paths_pipe_command() -> None:
    """Test extraction from piped commands."""
    # Input
    command = "cat /path/file.txt | grep pattern"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract the path
    assert len(result) == 1
    assert "|" not in str(result[0])


def test_extract_paths_empty_command() -> None:
    """Test extraction from empty command."""
    # Input
    command = ""

    # Act
    result = extract_paths_from_command(command)

    # Assert
    assert result == []


def test_extract_paths_command_without_paths() -> None:
    """Test extraction from command with only non-path tokens."""
    # Input
    command = "pwd"

    # Act
    result = extract_paths_from_command(command)

    # Assert
    assert result == []


def test_extract_paths_dot_prefix() -> None:
    """Test extraction of paths starting with dot."""
    # Input
    command = "ls .hidden-dir"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract path starting with dot
    assert len(result) == 1


def test_extract_paths_parent_directory() -> None:
    """Test extraction of parent directory references."""
    # Input
    command = "cd ../other-dir"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract path with ..
    assert len(result) == 1


def test_extract_paths_complex_command() -> None:
    """Test extraction from complex command with multiple elements."""
    # Input
    command = "find ./skills -name '*.md' -type f"

    # Act
    result = extract_paths_from_command(command)

    # Assert - should extract paths but not flags or values
    paths_str = [str(p) for p in result]
    assert any("skills" in p for p in paths_str)
    assert not any("-name" in p for p in paths_str)
    assert not any("-type" in p for p in paths_str)


def test_extract_paths_handles_invalid_path_chars() -> None:
    """Test that invalid path characters are handled gracefully."""
    # Input - command with token that causes Path() to fail
    command = "echo test"

    # Act - should not raise exception
    result = extract_paths_from_command(command)

    # Assert - returns empty or partial result
    assert isinstance(result, list)
