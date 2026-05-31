"""Construct the agent-harness ``Agent`` the backend serves.

A single shared model is built once; a fresh ``Agent`` is wired per request so
each conversation carries its own session (history). The toolset, system
prompt, and sandbox come from the rest of the ``penny`` package.
"""

from __future__ import annotations

import os

from agent_harness import Agent
from agent_harness.providers.openai import OpenAIProvider, OpenAIResponsesModel
from agent_harness.sessions.inmemory import InMemorySession

from .prompts import load_prompt
from .sandbox import get_sandbox
from .tools.registry import build_toolset


def build_model() -> OpenAIResponsesModel:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAIResponsesModel(provider=OpenAIProvider(api_key=api_key))


def build_agent(*, model: OpenAIResponsesModel, session: InMemorySession) -> Agent:
    return Agent(
        name="penny",
        model=model,
        instructions=load_prompt("system"),
        session=session,
        sandbox=get_sandbox(),
        toolsets=[build_toolset()],
    )
