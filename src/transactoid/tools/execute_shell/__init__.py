"""OpenAI runtime shell tool.

The Gemini runtime uses ADK's built-in ``EnvironmentToolset`` directly (see
``transactoid.core.runtime.gemini_runtime``), so only the OpenAI shim lives
here.
"""

__all__ = [
    "openai",
]
