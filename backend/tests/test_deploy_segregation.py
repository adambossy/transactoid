"""Import-boundary guardrail: the deploy domain and the app stay apart.

Per AGENTS.local.md ("Deploy vs. app", HARD CONSTRAINT), the dependency rule
is one-directional (deploy -> app). Application code must never import from
``deploy/``, read a ``fly.toml``/``schedules.json``, or branch on deployment
topology. Separately, the Typer CLI is a front door (app code, not
agent-internal): the agent domain (``penny/tools`` + the skills tree) must
never import ``penny.cli``.

This test fails the suite if a future change quietly couples the domains.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_PENNY_DIR = _BACKEND / "penny"
_TOOLS_DIR = _PENNY_DIR / "tools"
_SKILLS_DIR = _BACKEND / ".agent" / "skills"

_CLI_MODULE = "penny.cli"


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


def test_app_code_does_not_import_deploy() -> None:
    # input: every Python module in the application tree
    app_files = _python_files(_PENNY_DIR) + _python_files(_BACKEND / "tests")

    # act: collect any file that imports a top-level `deploy` package
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in app_files
        if any(
            _starts_with_any(module, ("deploy",)) for module in _imported_modules(path)
        )
    }

    # expected: application code never imports the deploy domain
    assert offenders == set()


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of string-constant nodes that are module/class/function docstrings.

    Docstrings legitimately *mention* deploy-config filenames (e.g. the CLI
    docstring says it never reads a ``fly.toml``); only string *literals used
    as code* (an ``open("fly.toml")``-style reference) should fail the guard.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Constant
                ):
                    ids.add(id(first.value))
    return ids


def _references_deploy_config_in_code(path: Path) -> bool:
    """True if a non-docstring string literal names a deploy-config file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc_ids = _docstring_nodes(tree)
    needles = ("fly.toml", "schedules.json")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in doc_ids
            and any(needle in node.value for needle in needles)
        ):
            return True
    return False


def test_app_code_does_not_read_deploy_config() -> None:
    # input: every application module (the app must not read a fly.toml /
    # schedules.json — docstrings that merely *mention* them are fine).
    app_files = _python_files(_PENNY_DIR)

    # act
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in app_files
        if _references_deploy_config_in_code(path)
    }

    # expected: nothing in the app references a deploy config file in code
    assert offenders == set()


def test_agent_domain_does_not_import_cli() -> None:
    # input: every module in the agent domain (tools + skills). The CLI is a
    # front door that drives the agent; the agent must never drive a front door.
    agent_files = _python_files(_TOOLS_DIR) + _python_files(_SKILLS_DIR)

    # act
    offenders = {
        str(path.relative_to(_BACKEND))
        for path in agent_files
        if any(
            _starts_with_any(module, (_CLI_MODULE,))
            for module in _imported_modules(path)
        )
    }

    # expected: the agent domain never imports penny.cli
    assert offenders == set()
