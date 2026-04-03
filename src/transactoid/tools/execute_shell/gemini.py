"""Filesystem tool for Gemini runtime with skill discovery and memory editing."""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

from loguru import logger

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.tools.execute_shell.policy import (
    MEMORY_DIR,
    REPORTS_DIR,
    evaluate_command_policy,
)


class GeminiFilesystemToolLogger:
    """Handles all logging for GeminiFilesystemTool with business logic separated."""

    def __init__(self, logger_instance: Any = logger) -> None:
        self._logger = logger_instance

    def blocked_command(
        self,
        runtime: str,
        reason: str,
        base_command: str,
        operation: str,
        command: str,
        effective_command: str,
        policy: str,
    ) -> None:
        """Log blocked execute_shell_command in copy/paste-friendly JSON format."""
        payload = {
            "runtime": runtime,
            "reason": reason,
            "base_command": base_command,
            "operation": operation,
            "command": command,
            "effective_command": effective_command,
            "policy": policy,
        }
        self._logger.warning(
            "BLOCKED_EXECUTE_SHELL_COMMAND {}",
            json.dumps(payload, separators=(",", ":")),
        )


class GeminiFilesystemTool:
    """Filesystem tool for Gemini ADK with policy enforcement.

    Allows scoped read/create/update/move/copy for skill discovery and memory/ editing.
    """

    def __init__(self, skill_paths: ResolvedSkillPaths) -> None:
        """Initialize with allowed skill directories and memory/.

        Args:
            skill_paths: Resolved skill paths defining allowed scope
        """
        # Include skill directories, memory, and reports directories
        # Always resolve() so paths match regardless of existence at init time
        self._allowed_roots = skill_paths.all_existing() + [
            MEMORY_DIR.resolve(),
            REPORTS_DIR.resolve(),
        ]
        self._logger = GeminiFilesystemToolLogger()

    async def execute_command(self, command: str) -> dict[str, Any]:
        """Execute shell command with policy enforcement.

        Args:
            command: Shell command to execute

        Returns:
            Command output or error message
        """
        # Evaluate command against policy
        policy_result = evaluate_command_policy(command, self._allowed_roots)

        if not policy_result.allowed:
            # Log blocked command in copy/paste-friendly format
            self._logger.blocked_command(
                runtime="gemini",
                reason=policy_result.reason,
                base_command=policy_result.base_command,
                operation=policy_result.operation,
                command=command,
                effective_command=policy_result.effective_command,
                policy="scoped read/create/update/move/copy for skills and memory/",
            )
            return {
                "error": "Command not allowed under scoped policy",
                "command": command,
                "reason": policy_result.reason,
                "policy": "Scoped read/create/update/move/copy for skills and memory/",
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
