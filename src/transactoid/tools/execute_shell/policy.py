"""Filesystem access policy for skill discovery and memory editing.

Scoped read/create/update/move/copy policy for OpenAI/Gemini runtimes, with
special permissions for the memory/ directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

__all__ = [
    "ALLOWED_COMMANDS",
    "DENIED_COMMANDS",
    "MEMORY_DIR",
    "REPORTS_DIR",
    "PolicyResult",
    "evaluate_command_policy",
    "is_path_in_scope",
    "is_memory_write_command",
]

# Directories the agent is allowed to read/write
MEMORY_DIR = Path(".transactoid/memory")
REPORTS_DIR = Path(".transactoid/reports")

# Shell commands allowed for skill discovery and memory editing
ALLOWED_COMMANDS = frozenset(
    {
        "pwd",
        "ls",
        "find",
        "cat",
        "head",
        "tail",
        "grep",
        "rg",
        "sed",
        "echo",
        "printf",
        "touch",
        "mkdir",
        "mv",
        "cp",
        "tree",
        # PDF extraction
        "pdftotext",
        # Python interpreter (used by pdfplumber and other PDF skills)
        "python",
        "python3",
    }
)

# Commands that must be blocked (destructive or package management)
DENIED_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "chmod",
        "chown",
        "ln",
        "dd",
        "truncate",
        "tee",
        "install",
        "pip",
        "npm",
        "yarn",
        "cargo",
        "apt",
        "yum",
        "brew",
    }
)


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """Result of policy evaluation."""

    allowed: bool
    reason: str
    base_command: str
    operation: str
    effective_command: str


def is_memory_write_command(command: str) -> bool:
    """Check if command is writing to memory/ directory.

    Args:
        command: Shell command string

    Returns:
        True if command targets memory/ directory
    """
    return "memory/" in command or MEMORY_DIR.name in command


def _strip_heredoc_body(command: str) -> str:
    """Strip heredoc body content from a command, keeping only the shell line.

    Given ``cat << 'EOF' > file.html\\n<html>...\\nEOF``, returns
    ``cat << 'EOF' > file.html``.

    Args:
        command: Shell command string, possibly multi-line with heredoc.

    Returns:
        The first line of the command (the shell invocation) with heredoc
        body removed.
    """
    # Detect heredoc operator on the first line
    first_line_end = command.find("\n")
    if first_line_end == -1:
        return command
    first_line = command[:first_line_end]
    if "<<" not in first_line:
        return command
    return first_line


def _split_chained_commands(command: str) -> list[str]:
    """Split a command string on shell chaining operators.

    Splits on ``&&``, ``||``, and ``;`` that appear outside of single
    or double quotes, returning individual sub-commands.

    Args:
        command: Shell command string, possibly chained.

    Returns:
        List of individual sub-command strings.
    """
    # Strip heredoc body first — chaining operators in content are irrelevant
    command = _strip_heredoc_body(command)

    parts: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    idx = 0
    length = len(command)

    while idx < length:
        char = command[idx]

        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
        elif char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
        elif not in_single and not in_double:
            # Check for &&
            if char == "&" and idx + 1 < length and command[idx + 1] == "&":
                chunk = "".join(current).strip()
                if chunk:
                    parts.append(chunk)
                current = []
                idx += 2
                continue
            # Check for ||
            if char == "|" and idx + 1 < length and command[idx + 1] == "|":
                chunk = "".join(current).strip()
                if chunk:
                    parts.append(chunk)
                current = []
                idx += 2
                continue
            # Check for ;
            if char == ";":
                chunk = "".join(current).strip()
                if chunk:
                    parts.append(chunk)
                current = []
                idx += 1
                continue
            current.append(char)
        else:
            current.append(char)

        idx += 1

    chunk = "".join(current).strip()
    if chunk:
        parts.append(chunk)

    return parts


def _extract_base_command(command: str) -> str:
    """Extract the base command from a shell command string.

    Args:
        command: Shell command string

    Returns:
        Base command (first word)
    """
    if not command.strip():
        return ""
    # Remove leading/trailing whitespace and get first word
    parts = command.strip().split()
    if not parts:
        return ""
    # Handle pipes
    return parts[0].split("|")[0].strip()


def _classify_operation(base_command: str, has_redirection: bool) -> str:
    """Classify the operation type of a command.

    Args:
        base_command: Base command name
        has_redirection: Whether command has redirection operators

    Returns:
        Operation type: read, write, move, copy, or unknown
    """
    if base_command in {"mv"}:
        return "move"
    if base_command in {"cp"}:
        return "copy"
    if base_command in {"touch", "mkdir"} or has_redirection:
        return "write"
    if base_command in ALLOWED_COMMANDS:
        return "read"
    return "unknown"


def _extract_paths_from_command_simple(command: str) -> list[str]:
    """Extract file paths from a command using simple heuristics.

    Args:
        command: Shell command string

    Returns:
        List of potential file paths
    """
    # Strip heredoc body so HTML content isn't parsed as paths
    command = _strip_heredoc_body(command)

    try:
        parts = shlex.split(command)
    except ValueError:
        # If shlex fails, fall back to simple split
        parts = command.split()

    base_cmd = _extract_base_command(command)
    paths = []

    for idx, part in enumerate(parts):
        # Skip flags and operators
        if part.startswith("-") or part in {">", ">>", "|", "<", "<<"}:
            continue
        # Skip the base command (first part)
        if idx == 0 or part == base_cmd:
            continue
        # Skip glob patterns (containing wildcards)
        if "*" in part or "?" in part or "[" in part:
            continue

        # A part is likely a path if:
        # 1. It contains a path separator (/)
        # 2. It starts with . or ~ (relative/home paths)
        # 3. It has a file extension (contains a dot after text)
        is_path = (
            "/" in part
            or part.startswith(".")
            or part.startswith("~")
            or ("." in part and not part.startswith("."))
        )

        if is_path:
            paths.append(part)

    return paths


def _validate_paths_in_scope(
    paths: list[str], allowed_roots: list[Path]
) -> tuple[bool, str]:
    """Validate that all paths are within allowed roots.

    Args:
        paths: List of path strings to validate
        allowed_roots: List of allowed root directories

    Returns:
        Tuple of (valid, reason) where valid is True if all paths are in scope
    """
    for path_str in paths:
        path = Path(path_str)
        if not is_path_in_scope(path, allowed_roots):
            return False, f"Path outside allowed scope: {path_str}"
    return True, ""


def evaluate_command_policy(
    command: str, allowed_roots: list[Path] | None = None
) -> PolicyResult:
    """Evaluate a shell command against the scoped policy.

    Args:
        command: Shell command string
        allowed_roots: List of allowed root directories (optional)

    Returns:
        PolicyResult with evaluation details
    """
    if allowed_roots is None:
        allowed_roots = []

    # Handle chained commands (&&, ||, ;) by evaluating each sub-command
    sub_commands = _split_chained_commands(command)
    if len(sub_commands) > 1:
        for sub_cmd in sub_commands:
            result = evaluate_command_policy(sub_cmd, allowed_roots)
            if not result.allowed:
                return PolicyResult(
                    allowed=False,
                    reason=result.reason,
                    base_command=result.base_command,
                    operation=result.operation,
                    effective_command=command,
                )
        # All sub-commands allowed
        return PolicyResult(
            allowed=True,
            reason="Command allowed",
            base_command=_extract_base_command(sub_commands[0]),
            operation="write",
            effective_command=command,
        )

    # Extract base command
    base_cmd = _extract_base_command(command)
    if not base_cmd:
        return PolicyResult(
            allowed=False,
            reason="Empty command",
            base_command="",
            operation="unknown",
            effective_command=command,
        )

    # Handle bash -c wrapper and python/python3 -c (inline code, not a path)
    effective_cmd = command
    if base_cmd in {"python", "python3"} and "-c" in command:
        return PolicyResult(
            allowed=True,
            reason="Command allowed",
            base_command=base_cmd,
            operation="read",
            effective_command=effective_cmd,
        )

    if base_cmd == "bash" and "-c" in command:
        # Extract inner command from bash -c
        try:
            parts = shlex.split(command)
            if "-c" in parts:
                c_idx = parts.index("-c")
                if c_idx + 1 < len(parts):
                    inner_cmd = parts[c_idx + 1]
                    # Evaluate the inner command recursively
                    # (chained commands are handled by the recursive call)
                    return evaluate_command_policy(inner_cmd, allowed_roots)
        except (ValueError, IndexError):
            return PolicyResult(
                allowed=False,
                reason="Invalid bash -c syntax",
                base_command=base_cmd,
                operation="unknown",
                effective_command=command,
            )

    # Check denylist first
    if base_cmd in DENIED_COMMANDS:
        return PolicyResult(
            allowed=False,
            reason=f"Command '{base_cmd}' is explicitly denied",
            base_command=base_cmd,
            operation="unknown",
            effective_command=effective_cmd,
        )

    # Check allowlist
    if base_cmd not in ALLOWED_COMMANDS:
        return PolicyResult(
            allowed=False,
            reason=f"Command '{base_cmd}' not in allowlist",
            base_command=base_cmd,
            operation="unknown",
            effective_command=effective_cmd,
        )

    # Classify operation (check redirection on the shell line only, not heredoc body)
    shell_line = _strip_heredoc_body(command)
    has_redirection = any(op in shell_line for op in {">", ">>", "<<", "<"})
    operation = _classify_operation(base_cmd, has_redirection)

    # For write operations (redirections), check if targeting allowed roots
    if has_redirection and operation == "write":
        # Extract paths and validate scope
        paths = _extract_paths_from_command_simple(command)
        if paths:
            valid, reason = _validate_paths_in_scope(paths, allowed_roots)
            if not valid:
                return PolicyResult(
                    allowed=False,
                    reason=reason,
                    base_command=base_cmd,
                    operation=operation,
                    effective_command=effective_cmd,
                )

    # For mv/cp, both source and destination must be in scope
    if operation in {"move", "copy"}:
        paths = _extract_paths_from_command_simple(command)
        if len(paths) < 2:
            return PolicyResult(
                allowed=False,
                reason=f"Invalid {operation} command: missing source or destination",
                base_command=base_cmd,
                operation=operation,
                effective_command=effective_cmd,
            )
        # Validate all paths (source and destination)
        valid, reason = _validate_paths_in_scope(paths, allowed_roots)
        if not valid:
            return PolicyResult(
                allowed=False,
                reason=reason,
                base_command=base_cmd,
                operation=operation,
                effective_command=effective_cmd,
            )

    # For read operations, validate paths are in scope
    if operation == "read":
        paths = _extract_paths_from_command_simple(command)
        if paths:
            valid, reason = _validate_paths_in_scope(paths, allowed_roots)
            if not valid:
                return PolicyResult(
                    allowed=False,
                    reason=reason,
                    base_command=base_cmd,
                    operation=operation,
                    effective_command=effective_cmd,
                )

    # Command passed all checks
    return PolicyResult(
        allowed=True,
        reason="Command allowed",
        base_command=base_cmd,
        operation=operation,
        effective_command=effective_cmd,
    )


def is_path_in_scope(path: Path, allowed_roots: list[Path]) -> bool:
    """Check if a path is within allowed skill directories.

    Args:
        path: Path to check
        allowed_roots: List of allowed root directories

    Returns:
        True if path is under one of the allowed roots
    """
    if not allowed_roots:
        return False

    try:
        resolved = path.resolve()
        for root in allowed_roots:
            if resolved == root or root in resolved.parents:
                return True
        return False
    except (OSError, ValueError):
        return False
