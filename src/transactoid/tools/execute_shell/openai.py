"""Shell tool for OpenAI runtime."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from agents import ShellTool


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


def create_shell_tool() -> Any:
    """Create a ShellTool for the OpenAI runtime.

    Returns:
        ShellTool instance with local shell execution
    """
    return ShellTool(
        name="execute_shell_command",
        executor=_local_shell_executor,
        environment={"type": "local"},
    )


__all__ = ["create_shell_tool"]
