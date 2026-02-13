"""Read-only filesystem tool for Gemini runtime skill discovery."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
from typing import Any

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.core.runtime.skills.policy import is_command_allowed, is_path_in_scope


class GeminiFilesystemTool:
    """Read-only filesystem tool for Gemini ADK with policy enforcement.

    Allows filesystem navigation for skill discovery but blocks mutating operations.
    """

    def __init__(self, skill_paths: ResolvedSkillPaths) -> None:
        """Initialize with allowed skill directories.

        Args:
            skill_paths: Resolved skill paths defining allowed scope
        """
        self._allowed_roots = skill_paths.all_existing()

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
        command_paths = self._extract_paths_from_command(command)
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

    def _extract_paths_from_command(self, command: str) -> list[Path]:
        """Extract file paths from command string for scope validation.

        Args:
            command: Shell command

        Returns:
            List of Path objects referenced in command
        """
        # Simple heuristic: look for tokens that look like paths
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


def create_gemini_filesystem_function_declaration() -> dict[str, Any]:
    """Create Gemini function declaration for filesystem tool.

    Returns:
        Function declaration dict for ADK
    """
    return {
        "name": "execute_shell_command",
        "description": (
            "Execute read-only shell commands for skill discovery. "
            "Allows: pwd, ls, find, cat, head, tail, grep, rg, sed. "
            "Restricted to skill directories only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Shell command to execute (read-only operations only)"
                    ),
                }
            },
            "required": ["command"],
        },
    }
