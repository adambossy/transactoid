"""Extract file paths from shell commands for validation."""

from __future__ import annotations

from pathlib import Path

__all__ = ["extract_paths_from_command"]


def extract_paths_from_command(command: str) -> list[Path]:
    """Extract file paths from command string for scope validation.

    Uses simple heuristics to identify tokens that look like paths:
    - Contains forward slash (/)
    - Starts with tilde (~)
    - Starts with dot (.)

    Limitations:
    - May miss relative paths without slashes (e.g., "cat file.txt")
    - Does not handle quoted paths with spaces
    - Glob patterns may not resolve correctly

    Args:
        command: Shell command

    Returns:
        List of Path objects referenced in command
    """
    paths: list[Path] = []
    tokens = command.split()

    for token in tokens:
        # Skip flags and operators
        if token.startswith("-") or token in {"|", "&&", "||", ";"}:
            continue

        # Try to interpret as path
        try:
            path = Path(token)
            if "/" in token or token.startswith("~") or token.startswith("."):
                paths.append(path.expanduser().resolve())
        except (ValueError, OSError):
            continue

    return paths
