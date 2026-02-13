"""Filesystem tool for Gemini runtime with skill discovery and memory editing."""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

from transactoid.core.runtime.skills.path_extraction import extract_paths_from_command
from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.core.runtime.skills.policy import (
    MEMORY_DIR,
    is_command_allowed,
    is_path_in_scope,
)


class GeminiFilesystemTool:
    """Filesystem tool for Gemini ADK with policy enforcement.

    Allows read-only skill discovery and read/write access to memory/ directory.
    """

    def __init__(self, skill_paths: ResolvedSkillPaths) -> None:
        """Initialize with allowed skill directories and memory/.

        Args:
            skill_paths: Resolved skill paths defining allowed scope
        """
        # Include both skill directories and memory/ directory
        self._allowed_roots = skill_paths.all_existing() + [
            MEMORY_DIR.resolve() if MEMORY_DIR.exists() else MEMORY_DIR
        ]

    async def execute_command(self, command: str) -> dict[str, Any]:
        """Execute shell command with policy enforcement.

        Args:
            command: Shell command to execute

        Returns:
            Command output or error message
        """
        # Validate command against allowlist
        if not is_command_allowed(command):
            return {
                "error": "Command not allowed under read-only policy",
                "command": command,
                "policy": "Only read operations are permitted for skill discovery",
            }

        # Extract paths from command for scope validation
        command_paths = extract_paths_from_command(command)
        for cmd_path in command_paths:
            if not is_path_in_scope(cmd_path, self._allowed_roots):
                return {
                    "error": "Path outside allowed skill directories",
                    "path": str(cmd_path),
                    "allowed_roots": [str(root) for root in self._allowed_roots],
                }

        # Execute command via subprocess (shell=False for security)
        # S603 is acceptable here because command is validated by policy allowlist
        try:
            args = shlex.split(command)
            result = subprocess.run(  # noqa: S603
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            output = result.stdout if result.returncode == 0 else result.stderr
            return {
                "output": output,
                "command": command,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "error": "Command execution timed out",
                "command": command,
            }
        except Exception as e:
            return {
                "error": f"Command execution failed: {e}",
                "command": command,
            }


__all__ = ["GeminiFilesystemTool"]
