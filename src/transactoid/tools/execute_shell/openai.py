"""Filesystem tool for OpenAI runtime with skill discovery and memory editing."""

from __future__ import annotations

import json
from typing import Any

from agents import ShellTool
from loguru import logger

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.tools.execute_shell.policy import (
    MEMORY_DIR,
    evaluate_command_policy,
)


class OpenAIFilesystemToolLogger:
    """Handles all logging for OpenAI filesystem tool with business logic separated."""

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


def create_scoped_shell_tool(skill_paths: ResolvedSkillPaths) -> Any:
    """Create a ShellTool with policy enforcement for skills and memory/.

    Args:
        skill_paths: Resolved skill paths defining allowed scope

    Returns:
        ShellTool instance with approval function for policy enforcement
    """
    # Include both skill directories and memory/ directory
    allowed_roots = skill_paths.all_existing() + [
        MEMORY_DIR.resolve() if MEMORY_DIR.exists() else MEMORY_DIR
    ]

    # Create logger instance
    tool_logger = OpenAIFilesystemToolLogger()

    def approval_function(ctx: Any, action: Any, command: str) -> bool:
        """Check if command is allowed under scoped policy.

        Args:
            ctx: Run context wrapper
            action: Shell action request
            command: Shell command to execute

        Returns:
            True if command is allowed, False otherwise
        """
        # Evaluate command against policy
        policy_result = evaluate_command_policy(command, allowed_roots)

        if not policy_result.allowed:
            # Log blocked command in copy/paste-friendly format
            tool_logger.blocked_command(
                runtime="openai",
                reason=policy_result.reason,
                base_command=policy_result.base_command,
                operation=policy_result.operation,
                command=command,
                effective_command=policy_result.effective_command,
                policy="scoped read/create/update/move/copy for skills and memory/",
            )
            return False

        return True

    # Note: ShellTool with local environment creates a default local executor
    # when executor parameter is None
    return ShellTool(
        name="execute_shell_command",
        needs_approval=approval_function,
        environment={"type": "local"},
    )


__all__ = ["create_scoped_shell_tool"]
