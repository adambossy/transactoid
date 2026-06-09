"""Construct the agent-harness ``Agent`` the backend serves.

One shared ``Agent`` factory; a fresh ``Agent`` is built per request so each
conversation carries its own session. Tools come from four sources:

- :func:`build_toolset` — Penny's core domain tools.
- :func:`build_amazon_toolset` — Amazon plugin (self-contained subpackage).
- :class:`FilesystemTools` — read/write/edit/grep/glob/list_dir on the
  workspace sandbox.
- :func:`build_skill_tool` — progressive-disclosure skill registry.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from agent_harness import Agent
from agent_harness.core.filesystem import FilesystemTools
from agent_harness.core.skills import SkillRegistry, build_skill_tool
from agent_harness.providers.openai import OpenAIProvider, OpenAIResponsesModel
from agent_harness.sessions.inmemory import InMemorySession

from .plugins.amazon import build_amazon_toolset
from .prompts import load_prompt
from .sandbox import get_sandbox
from .tools.registry import build_toolset


def _sql_dialect_from_env() -> str:
    """Return ``postgresql`` or ``sqlite`` based on ``$DATABASE_URL``."""
    url = os.environ.get("DATABASE_URL", "").strip().lower()
    if url.startswith(("postgres://", "postgresql://", "postgresql+", "postgres+")):
        return "postgresql"
    return "sqlite"


_CORE_MEMORY_FILES = ("index.md", "merchant-rules.md")


def _assemble_agent_memory() -> str:
    """Concatenate the core memory files from the workspace.

    Mirrors main's behavior: read ``index.md`` then ``merchant-rules.md``
    from ``~/.transactoid/memory/`` (joined with blank lines). Empty string
    if neither exists.
    """
    from .workspace import resolve_memory_dir

    memory_dir = resolve_memory_dir()
    if not memory_dir.exists() or not memory_dir.is_dir():
        return ""
    parts: list[str] = []
    for name in _CORE_MEMORY_FILES:
        path = memory_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def _render_system_prompt() -> str:
    """Render system.md with full runtime context.

    Fills: today's date + ISO week, DB dialect + dialect directives, schema
    snapshot, taxonomy snapshot, taxonomy rules, and agent memory.
    """
    import yaml  # local import — keeps top-level import cost light
    from .services import get_taxonomy
    from .db import get_db

    today = date.today()
    week_start = today - timedelta(days=today.isoweekday() - 1)
    week_end = week_start + timedelta(days=6)
    dialect = _sql_dialect_from_env()

    # Heavy blocks — produced fresh per request so taxonomy edits / schema
    # migrations during the session are reflected immediately.
    try:
        schema_yaml = yaml.dump(
            get_db().compact_schema_hint(), default_flow_style=False, sort_keys=False
        )
    except Exception:
        schema_yaml = "(schema unavailable)"
    try:
        taxonomy_yaml = yaml.dump(
            get_taxonomy().to_prompt(), default_flow_style=False, sort_keys=False
        )
    except Exception:
        taxonomy_yaml = "(taxonomy unavailable)"
    try:
        taxonomy_rules = load_prompt("taxonomy-rules")
    except Exception:
        taxonomy_rules = "(taxonomy rules unavailable)"
    try:
        sql_directives = load_prompt(f"sql-directives-{dialect}")
    except Exception:
        sql_directives = ""

    replacements = {
        "{{CURRENT_DATE}}": today.isoformat(),
        "{{CURRENT_WEEKDAY}}": today.strftime("%A"),
        "{{WEEK_START}}": week_start.isoformat(),
        "{{WEEK_END}}": week_end.isoformat(),
        "{{SQL_DIALECT}}": dialect,
        "{{SQL_DIALECT_DIRECTIVES}}": sql_directives,
        "{{DATABASE_SCHEMA}}": schema_yaml,
        "{{CATEGORY_TAXONOMY}}": taxonomy_yaml,
        "{{TAXONOMY_RULES}}": taxonomy_rules,
        "{{AGENT_MEMORY}}": _assemble_agent_memory() or "(no memory files yet)",
    }
    rendered = load_prompt("system")
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered

_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # .../backend/


def build_model() -> OpenAIResponsesModel:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAIResponsesModel(provider=OpenAIProvider(api_key=api_key))


def build_agent(*, model: OpenAIResponsesModel, session: InMemorySession) -> Agent:
    sandbox = get_sandbox()

    skill_registry = SkillRegistry.load(project_root=_PROJECT_ROOT, user_root=None)
    skill_tool = build_skill_tool(skill_registry)

    from agent_harness import StaticToolset
    skills_toolset = StaticToolset(name="skills", tools=[skill_tool])
    filesystem_tools = FilesystemTools(sandbox=sandbox)

    return Agent(
        name="penny",
        model=model,
        instructions=_render_system_prompt(),
        session=session,
        sandbox=sandbox,
        toolsets=[
            build_toolset(),
            build_amazon_toolset(),
            filesystem_tools,
            skills_toolset,
        ],
    )
