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
_BILLING_DIR = _BACKEND / "penny" / "billing"

# Website-owned data packages the agent domain must never import (both hold
# app data out of the run_sql blast radius; billing additionally holds secrets).
_WEBSITE_DATA_MODULES = ("penny.api.persistence", "penny.billing")
_FORBIDDEN_FOR_PERSISTENCE = ("penny.tools", "penny.agent_factory")


def _module_to_path(module: str) -> Path | None:
    """Resolve a ``penny.*`` module name to its source file, or ``None``."""
    if not (module == "penny" or module.startswith("penny.")):
        return None
    base = _BACKEND / Path(*module.split("."))
    candidate = base.with_suffix(".py")
    if candidate.exists():
        return candidate
    init = base / "__init__.py"
    return init if init.exists() else None


def _file_package(path: Path) -> str:
    """The dotted package that a file's relative imports resolve against."""
    rel = path.relative_to(_BACKEND).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]  # a package __init__'s package is the package itself
    else:
        parts = parts[:-1]  # a module's package is its containing directory
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    """Absolute ``penny.*`` module names a file imports (relatives resolved).

    ``from .foo import x`` / ``from ..bar import y`` are resolved against the
    file's own package so the transitive walk can follow intra-package edges,
    not just absolute imports.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _file_package(path)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    modules.add(node.module)
                continue
            # Relative import: ascend ``level - 1`` packages from ``package``.
            base_parts = package.split(".") if package else []
            ascend = node.level - 1
            base_parts = (
                base_parts[: len(base_parts) - ascend] if ascend else base_parts
            )
            resolved = base_parts + (node.module.split(".") if node.module else [])
            if resolved:
                modules.add(".".join(resolved))
    return modules


def _transitive_penny_imports(entry: Path) -> set[str]:
    """Every ``penny.*`` module name reachable from ``entry`` via import edges."""
    reachable: set[str] = set()
    visited_paths = {entry}
    stack = [entry]
    while stack:
        for module in _imported_modules(stack.pop()):
            if not (module == "penny" or module.startswith("penny.")):
                continue
            reachable.add(module)
            target = _module_to_path(module)
            if target is not None and target not in visited_paths:
                visited_paths.add(target)
                stack.append(target)
    return reachable


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _starts_with_any(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def test_agent_domain_does_not_import_persistence():
    # input: every entry module in the agent domain (tools + skills)
    agent_files = _python_files(_TOOLS_DIR) + _python_files(_SKILLS_DIR)

    # act: walk the FULL import graph from each entry and collect any that reach
    # a website data package (persistence or the billing vault/ledger) — directly
    # or through an intermediary module (e.g. an old top-level penny.onboarding).
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in agent_files
        if any(
            _starts_with_any(module, _WEBSITE_DATA_MODULES)
            for module in _transitive_penny_imports(path)
        )
    }

    # expected: nothing in the agent domain reaches the website store/billing
    assert offenders == set()


def test_persistence_does_not_import_agent_domain():
    # input: every module in the website data packages (persistence + billing)
    website_files = _python_files(_PERSISTENCE_DIR) + _python_files(_BILLING_DIR)

    # act: collect files importing penny.tools / penny.agent_factory
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in website_files
        if any(
            _starts_with_any(module, _FORBIDDEN_FOR_PERSISTENCE)
            for module in _imported_modules(path)
        )
    }

    # expected: the website data packages never import the agent domain
    assert offenders == set()
