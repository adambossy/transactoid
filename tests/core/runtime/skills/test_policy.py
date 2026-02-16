"""Tests for filesystem policy enforcement."""

from pathlib import Path

from transactoid.core.runtime.skills.policy import (
    evaluate_command_policy,
    is_path_in_scope,
)


def test_evaluate_command_policy_read_commands(tmp_path: Path) -> None:
    """Test that read commands are allowed within scope."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed_file = allowed_dir / "test.txt"
    allowed_file.touch()
    allowed_roots = [allowed_dir]

    # Input - allowed read commands
    commands = [
        f"ls {allowed_dir}",
        f"cat {allowed_file}",
        f"grep pattern {allowed_file}",
        f"find {allowed_dir} -name '*.md'",
        "pwd",
        f"head -n 10 {allowed_file}",
        f"tail -f {allowed_file}",
        f"rg --files {allowed_dir}",
        f"sed -n '1,10p' {allowed_file}",
        f"tree {allowed_dir}",
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert result.allowed, f"Command should be allowed: {command}"
        assert result.operation == "read" or result.base_command == "tree"


def test_evaluate_command_policy_write_commands(tmp_path: Path) -> None:
    """Test that write commands are allowed within scope."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed_roots = [allowed_dir]

    # Input - allowed write commands
    commands = [
        f"touch {allowed_dir}/newfile.txt",
        f"mkdir {allowed_dir}/newdir",
        f"echo 'text' > {allowed_dir}/output.txt",
        f"echo 'text' >> {allowed_dir}/output.txt",
        f"printf 'text' > {allowed_dir}/output.txt",
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert result.allowed, f"Command should be allowed: {command}"
        assert result.operation == "write"


def test_evaluate_command_policy_move_copy_commands(tmp_path: Path) -> None:
    """Test that mv and cp commands are allowed when both paths are in scope."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    source = allowed_dir / "source.txt"
    source.touch()
    dest = allowed_dir / "dest.txt"
    allowed_roots = [allowed_dir]

    # Input - allowed move/copy commands
    commands = [
        f"mv {source} {dest}",
        f"cp {source} {dest}",
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert result.allowed, f"Command should be allowed: {command}"
        assert result.operation in {"move", "copy"}


def test_evaluate_command_policy_move_copy_denied_outside_scope(
    tmp_path: Path,
) -> None:
    """Test that mv/cp are denied when either path is outside scope."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    outside_dir = tmp_path / "outside"
    allowed_dir.mkdir()
    outside_dir.mkdir()
    source_in = allowed_dir / "source.txt"
    source_out = outside_dir / "source.txt"
    dest_in = allowed_dir / "dest.txt"
    dest_out = outside_dir / "dest.txt"
    source_in.touch()
    source_out.touch()
    allowed_roots = [allowed_dir]

    # Input - denied move/copy commands
    commands = [
        f"mv {source_in} {dest_out}",  # source in, dest out
        f"mv {source_out} {dest_in}",  # source out, dest in
        f"cp {source_in} {dest_out}",  # source in, dest out
        f"cp {source_out} {dest_in}",  # source out, dest in
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert not result.allowed, f"Command should be denied: {command}"
        assert "outside allowed scope" in result.reason.lower()


def test_evaluate_command_policy_bash_c_allowed(tmp_path: Path) -> None:
    """Test that bash -c is allowed for single allowed commands."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed_file = allowed_dir / "test.txt"
    allowed_file.touch()
    allowed_roots = [allowed_dir]

    # Input - allowed bash -c commands
    commands = [
        f'bash -c "echo text >> {allowed_file}"',
        f'bash -c "ls {allowed_dir}"',
        f'bash -c "cat {allowed_file}"',
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert result.allowed, f"Command should be allowed: {command}"


def test_evaluate_command_policy_bash_c_chained_denied(tmp_path: Path) -> None:
    """Test that bash -c with chained commands is denied."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    allowed_roots = [allowed_dir]

    # Input - denied chained bash -c commands
    commands = [
        f'bash -c "ls {allowed_dir} && echo done"',
        'bash -c "cat file.txt || echo failed"',
        'bash -c "ls; pwd"',
        'bash -c "ls | grep pattern"',
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert not result.allowed, f"Command should be denied: {command}"
        assert "chained" in result.reason.lower()


def test_evaluate_command_policy_denied_commands() -> None:
    """Test that explicitly denied commands are blocked."""
    # Input - denied commands
    commands = [
        "rm file.txt",
        "rmdir olddir",
        "chmod 755 file.txt",
        "pip install package",
        "npm install",
        "apt install vim",
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, None)
        assert not result.allowed, f"Command should be denied: {command}"
        assert "denied" in result.reason.lower()


def test_evaluate_command_policy_unknown_command() -> None:
    """Test that unknown commands are blocked."""
    # Input
    command = "unknown_command arg1 arg2"

    # Act
    result = evaluate_command_policy(command, None)

    # Assert
    assert not result.allowed
    assert "not in allowlist" in result.reason.lower()


def test_evaluate_command_policy_empty_command() -> None:
    """Test that empty command is blocked."""
    # Act
    result = evaluate_command_policy("", None)

    # Assert
    assert not result.allowed
    assert result.reason == "Empty command"


def test_evaluate_command_policy_redirection_outside_scope(tmp_path: Path) -> None:
    """Test that redirection to paths outside scope is denied."""
    # Setup
    allowed_dir = tmp_path / "allowed"
    outside_dir = tmp_path / "outside"
    allowed_dir.mkdir()
    outside_dir.mkdir()
    outside_file = outside_dir / "output.txt"
    allowed_roots = [allowed_dir]

    # Input - denied redirection commands
    commands = [
        f"echo 'text' > {outside_file}",
        f"echo 'text' >> {outside_file}",
        f"cat input.txt > {outside_file}",
    ]

    # Act & Assert
    for command in commands:
        result = evaluate_command_policy(command, allowed_roots)
        assert not result.allowed, f"Command should be denied: {command}"
        assert "outside allowed scope" in result.reason.lower()


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
