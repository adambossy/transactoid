"""Filesystem access policy for skill discovery and memory editing.

Read-only command and path allowlists for OpenAI/Gemini runtimes, with
special permissions for the memory/ directory.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ALLOWED_COMMANDS",
    "DENIED_COMMANDS",
    "MEMORY_DIR",
    "is_command_allowed",
    "is_path_in_scope",
    "is_memory_write_command",
]

# Memory directory that can be written to
MEMORY_DIR = Path("memory")

# Read-only shell commands allowed for skill discovery
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
        "echo",  # Needed for appending to files
    }
)

# Commands that must be blocked (mutating operations)
DENIED_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "mv",
        "cp",
        "touch",
        "mkdir",
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


def is_memory_write_command(command: str) -> bool:
    """Check if command is writing to memory/ directory.

    Args:
        command: Shell command string

    Returns:
        True if command targets memory/ directory
    """
    return "memory/" in command or MEMORY_DIR.name in command


def is_command_allowed(command: str) -> bool:
    """Check if a shell command is allowed under policy.

    Args:
        command: Shell command string

    Returns:
        True if command is in allowlist and not in denylist
    """
    # Extract base command (first word before space or pipe)
    base_cmd = command.strip().split()[0] if command.strip() else ""
    base_cmd = base_cmd.split("|")[0].strip()

    # Allow redirection operators for memory/ directory
    has_redirection = any(op in command for op in {">", ">>", "<<", "<"})
    if has_redirection:
        if is_memory_write_command(command):
            # Allow write operations to memory/ directory
            return base_cmd in ALLOWED_COMMANDS or base_cmd == "cat"
        # Block write operations elsewhere
        return False

    # Check denylist first (explicit blocks)
    if base_cmd in DENIED_COMMANDS:
        return False

    # Check allowlist
    return base_cmd in ALLOWED_COMMANDS


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
