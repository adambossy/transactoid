"""Import-boundary guardrail: agent domain and website persistence stay apart.

Per AGENTS.local.md ("Architectural segregation"), the dependency rule is
one-directional (website -> agent). This test fails the suite if a future
change quietly recouples the two domains, so it is caught at CI time.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _BACKEND / "penny" / "tools"
_SKILLS_DIR = _BACKEND / ".agent" / "skills"
_PERSISTENCE_DIR = _BACKEND / "penny" / "api" / "persistence"

_PERSISTENCE_MODULE = "penny.api.persistence"
_FORBIDDEN_FOR_PERSISTENCE = ("penny.tools", "penny.agent_factory")


def _imported_modules(path: Path) -> set[str]:
    """Return the set of module names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _starts_with_any(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def test_agent_domain_does_not_import_persistence():
    # input: every module in the agent domain (tools + skills)
    agent_files = _python_files(_TOOLS_DIR) + _python_files(_SKILLS_DIR)

    # act: collect any file that imports the website persistence package
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in agent_files
        if any(
            _starts_with_any(module, (_PERSISTENCE_MODULE,))
            for module in _imported_modules(path)
        )
    }

    # expected: nothing in the agent domain reaches the website store
    assert offenders == set()


def test_persistence_does_not_import_agent_domain():
    # input: every module in the website persistence package
    persistence_files = _python_files(_PERSISTENCE_DIR)

    # act: collect persistence files importing penny.tools / penny.agent_factory
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in persistence_files
        if any(
            _starts_with_any(module, _FORBIDDEN_FOR_PERSISTENCE)
            for module in _imported_modules(path)
        )
    }

    # expected: the persistence package never imports the agent domain
    assert offenders == set()
