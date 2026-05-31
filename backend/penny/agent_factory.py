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
        instructions=load_prompt("system"),
        session=session,
        sandbox=sandbox,
        toolsets=[
            build_toolset(),
            build_amazon_toolset(),
            filesystem_tools,
            skills_toolset,
        ],
    )
