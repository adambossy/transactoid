"""Filesystem tool for OpenAI runtime with skill discovery and memory editing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from agents import ShellTool
from loguru import logger

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.tools.execute_shell.policy import evaluate_command_policy


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


def _local_shell_executor(request: Any) -> str:
    """Execute a local shell call for OpenAI ShellTool local environment."""
    action = request.data.action
    timeout_seconds = None
    if action.timeout_ms is not None:
        timeout_seconds = action.timeout_ms / 1000

    env = os.environ.copy()
    output_chunks: list[str] = []
    for command in action.commands:
        result = subprocess.run(  # noqa: S602
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        output_chunks.append(
            f"command={command}\n"
            f"exit_code={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return "\n\n".join(output_chunks)


def create_scoped_shell_tool(
    skill_paths: ResolvedSkillPaths,
    *,
    memory_dir: Path,
    reports_dir: Path,
) -> Any:
    """Create a ShellTool with policy enforcement for skills and memory.

    Args:
        skill_paths: Resolved skill paths defining allowed scope
        memory_dir: Workspace memory directory
        reports_dir: Workspace reports directory

    Returns:
        ShellTool instance with approval function for policy enforcement
    """
    # Always resolve() so paths match regardless of existence at init time
    allowed_roots = skill_paths.all_existing() + [
        memory_dir.resolve(),
        reports_dir.resolve(),
    ]

    # Create logger instance
    tool_logger = OpenAIFilesystemToolLogger()

    def approval_function(ctx: Any, action: Any, call_id: str) -> bool:
        """Check if command is allowed under scoped policy.

        Args:
            ctx: Run context wrapper
            action: Shell action request
            call_id: Shell tool call identifier

        Returns:
            True if command is allowed, False otherwise
        """
        commands: list[str] = []
        if hasattr(action, "commands"):
            commands = [str(item) for item in getattr(action, "commands", [])]

        for command in commands:
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
                    policy=(
                        "scoped read/create/update/move/copy for skills and memory/"
                    ),
                )
                return False

        return True

    return ShellTool(
        name="execute_shell_command",
        executor=_local_shell_executor,
        needs_approval=approval_function,
        environment={"type": "local"},
    )


__all__ = ["create_scoped_shell_tool"]
