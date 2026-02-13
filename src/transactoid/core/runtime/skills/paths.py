"""Resolve and normalize skill directory paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["ResolvedSkillPaths", "resolve_skill_paths", "find_available_skills"]


@dataclass(frozen=True, slots=True)
class ResolvedSkillPaths:
    """Resolved skill directory paths with precedence order."""

    project_dir: Path | None
    user_dir: Path | None
    builtin_dir: Path | None

    def all_existing(self) -> list[Path]:
        """Return existing dirs in precedence order (project > user > builtin)."""
        paths: list[Path] = []
        if self.project_dir is not None:
            paths.append(self.project_dir)
        if self.user_dir is not None:
            paths.append(self.user_dir)
        if self.builtin_dir is not None:
            paths.append(self.builtin_dir)
        return paths


def resolve_skill_paths(
    *,
    project_dir: str,
    user_dir: str,
    builtin_dir: str,
) -> ResolvedSkillPaths:
    """Resolve and expand skill directory paths.

    Args:
        project_dir: Project-local skill directory (e.g., ".claude/skills")
        user_dir: User-global skill directory (e.g., "~/.claude/skills")
        builtin_dir: Built-in skill directory (e.g., "src/transactoid/skills")

    Returns:
        ResolvedSkillPaths with absolute paths for existing directories.
        Non-existent directories are set to None (non-fatal).
    """
    project_path = _resolve_if_exists(project_dir)
    user_path = _resolve_if_exists(user_dir)
    builtin_path = _resolve_if_exists(builtin_dir)

    return ResolvedSkillPaths(
        project_dir=project_path,
        user_dir=user_path,
        builtin_dir=builtin_path,
    )


def find_available_skills(paths: ResolvedSkillPaths) -> list[Path]:
    """Find all valid SKILL.md files in skill directories.

    Scans skill directories in precedence order (project > user > builtin)
    and returns paths to SKILL.md files that exist and are readable.

    Args:
        paths: Resolved skill directory paths

    Returns:
        List of Path objects pointing to valid SKILL.md files, ordered by
        precedence (project skills first, then user, then builtin)
    """
    skills: list[Path] = []
    for root in paths.all_existing():
        try:
            for item in root.iterdir():
                if item.is_dir():
                    skill_file = item / "SKILL.md"
                    if skill_file.exists() and skill_file.is_file():
                        skills.append(skill_file)
        except (OSError, PermissionError):
            # Skip directories that can't be read
            continue
    return skills


def _resolve_if_exists(path_str: str) -> Path | None:
    """Expand and normalize path, return absolute Path if exists, else None."""
    if not path_str:
        return None
    expanded = Path(path_str).expanduser().resolve()
    if expanded.exists() and expanded.is_dir():
        return expanded
    return None
