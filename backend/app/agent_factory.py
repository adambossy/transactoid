"""Construct the agent-harness ``Agent`` the backend serves.

A single shared model is built once; a fresh ``Agent`` is wired per request so
each conversation can carry its own session (history).
"""

from __future__ import annotations

import os

from agent_harness import Agent, StaticToolset, tool
from agent_harness.providers.openai import OpenAIProvider, OpenAIResponsesModel
from agent_harness.sessions.inmemory import InMemorySession

INSTRUCTIONS = (
    "You are Transactoid, a concise and helpful assistant. "
    "When the user asks about the weather, call the get_weather tool."
)


@tool
async def get_weather(city: str) -> str:
    """Look up the current weather for a city.

    Args:
        city: Name of the city to look up.
    """
    return f"It's 18C and partly cloudy in {city}."


def build_model() -> OpenAIResponsesModel:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAIResponsesModel(provider=OpenAIProvider(api_key=api_key))


def build_agent(*, model: OpenAIResponsesModel, session: InMemorySession) -> Agent:
    return Agent(
        name="transactoid",
        model=model,
        instructions=INSTRUCTIONS,
        session=session,
        toolsets=[StaticToolset(name="tools", tools=[get_weather])],
    )
