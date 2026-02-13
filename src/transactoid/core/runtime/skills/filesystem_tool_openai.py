"""Read-only filesystem tool for OpenAI runtime skill discovery."""

from __future__ import annotations

from typing import Any

from agents import ShellTool

from transactoid.core.runtime.skills.path_extraction import extract_paths_from_command
from transactoid.core.runtime.skills.paths import ResolvedSkillPaths
from transactoid.core.runtime.skills.policy import is_command_allowed, is_path_in_scope


def create_readonly_shell_tool(skill_paths: ResolvedSkillPaths) -> Any:
    """Create a ShellTool with read-only policy enforcement.

    Args:
        skill_paths: Resolved skill paths defining allowed scope

    Returns:
        ShellTool instance with approval function for policy enforcement
    """
    allowed_roots = skill_paths.all_existing()

    def approval_function(ctx: Any, action: Any, command: str) -> bool:
        """Check if command is allowed under read-only policy.

        Args:
            ctx: Run context wrapper
            action: Shell action request
            command: Shell command to execute

        Returns:
            True if command is allowed, False otherwise
        """
        # Validate command against allowlist
        if not is_command_allowed(command):
            return False

        # Extract paths from command for scope validation
        command_paths = extract_paths_from_command(command)
        for cmd_path in command_paths:
            if not is_path_in_scope(cmd_path, allowed_roots):
                return False

        return True

    # Note: ShellTool with local environment creates a default local executor
    # when executor parameter is None
    return ShellTool(
        name="read_skill_files",
        needs_approval=approval_function,
        environment={"type": "local"},
    )


__all__ = ["create_readonly_shell_tool"]
