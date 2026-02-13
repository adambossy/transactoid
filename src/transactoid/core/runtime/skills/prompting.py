"""Generate skill usage instructions for agent prompts."""

from __future__ import annotations

from transactoid.core.runtime.skills.paths import ResolvedSkillPaths

__all__ = ["generate_skill_instructions"]


def generate_skill_instructions(paths: ResolvedSkillPaths) -> str:
    """Generate compact skill discovery and usage instructions.

    Args:
        paths: Resolved skill directory paths

    Returns:
        Instruction text to inject into agent prompt
    """
    existing = paths.all_existing()
    if not existing:
        return ""

    location_lines = [
        "# Agent Skills",
        "",
        "Skills extend your capabilities. Discover and use them as follows:",
        "",
        "## Skill Locations (in precedence order)",
        "",
    ]

    if paths.project_dir is not None:
        location_lines.append(f"1. Project: `{paths.project_dir}`")
    if paths.user_dir is not None:
        location_lines.append(f"2. User: `{paths.user_dir}`")
    if paths.builtin_dir is not None:
        location_lines.append(f"3. Built-in: `{paths.builtin_dir}`")

    location_lines.extend(
        [
            "",
            "## Usage Protocol",
            "",
            "1. **Discovery**: Use filesystem tools to search skill directories",
            "   - List directories to find available skills",
            "   - Each skill is a directory containing a `SKILL.md` file",
            "",
            "2. **Loading**: Read the `SKILL.md` file from the skill directory",
            "   - The file contains instructions for using the skill",
            "   - Follow the instructions exactly as written",
            "",
            "3. **Precedence**: If duplicate skill names exist:",
            "   - Project skills override user skills",
            "   - User skills override built-in skills",
            "   - Always prefer the skill with highest precedence",
            "",
            "4. **Execution**: Apply skill instructions to relevant tasks",
            "   - Skills may provide prompts, workflows, or tool usage patterns",
            "   - Integrate skill guidance into your response strategy",
            "",
        ]
    )

    return "\n".join(location_lines)
