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

from datetime import date, timedelta
import os
from pathlib import Path

from agent_harness import Agent
from agent_harness.core.filesystem import FilesystemTools
from agent_harness.core.models import ModelSettings
from agent_harness.core.skills import SkillRegistry, build_skill_tool
from agent_harness.providers.google import GeminiModel, GoogleProvider
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
    """Render the penny-system-prompt prompt with full runtime context.

    Fills: today's date + ISO week, DB dialect + dialect directives, schema
    snapshot, taxonomy snapshot, and agent memory. (taxonomy-rules is NOT
    injected here — that 35 KB block belongs to the categorizer prompt;
    main never put it in the agent loop either.)
    """
    import yaml  # local import — keeps top-level import cost light

    from .db import get_db
    from .services import get_taxonomy

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
        "{{AGENT_MEMORY}}": _assemble_agent_memory() or "(no memory files yet)",
    }
    rendered = load_prompt("penny-system-prompt")
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # .../backend/


def build_model() -> GeminiModel:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    # Pin to the model the user picked (defaults to GEMINI_3_5_FLASH inside
    # agent-harness, but be explicit so it's visible in code review).
    return GeminiModel(
        provider=GoogleProvider(api_key=api_key), name="gemini-3.5-flash"
    )


def _thinking_budget_from_env() -> int:
    """Thinking-token budget passed to the model (``PENNY_AGENT_THINKING_BUDGET``).

    Gemini semantics: ``-1`` = dynamic (model decides how much to think),
    ``0`` would disable thinking entirely. Must be set to a non-None value or
    the provider omits ``thinking_config`` and Gemini streams no thought
    summaries — the UI then shows nothing between tool calls while the model
    thinks.
    """
    raw = os.environ.get("PENNY_AGENT_THINKING_BUDGET", "").strip()
    return int(raw) if raw else -1


def build_agent(
    *,
    model: GeminiModel,
    session: InMemorySession,
    persist_session: bool = True,
) -> Agent:
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
        persist_session=persist_session,
        sandbox=sandbox,
        model_settings=ModelSettings(thinking_budget=_thinking_budget_from_env()),
        toolsets=[
            build_toolset(),
            build_amazon_toolset(),
            filesystem_tools,
            skills_toolset,
        ],
    )
