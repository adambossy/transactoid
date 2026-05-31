"""Shell-exec tool — thin wrapper over the agent-harness ``Sandbox.exec`` primitive.

This is the harness-native replacement for the prior ``execute_shell`` MCP
tool. Commands are argv lists (no shell interpretation); execution is
scoped to the workspace sandbox.
"""

from __future__ import annotations

from typing import Any

from agent_harness import tool

from ..sandbox import get_sandbox


@tool
async def bash(
    cmd: list[str],
    cwd: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run a command in the workspace sandbox.

    The first list element is the program; remaining elements are
    arguments. No shell interpretation — pipes/redirects need explicit
    ``sh -c``. Stdout/stderr are returned as text.

    Args:
        cmd: argv list (e.g. ``["ls", "-la"]``).
        cwd: Optional working directory relative to the sandbox root.
        timeout: Max seconds to wait before killing the process.

    Returns:
        ``{"stdout": str, "stderr": str, "exit_code": int}``.
    """
    sandbox = get_sandbox()
    result = await sandbox.exec(cmd, cwd=cwd, timeout=timeout)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }
