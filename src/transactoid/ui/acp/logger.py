"""Logging for ACP server components.

Separates logging logic from business logic per AGENTS.md guidelines.
"""

from __future__ import annotations

from typing import Any

import loguru
from loguru import logger

MAX_LOG_LINE_LENGTH = 1000


def _truncate(value: Any, max_len: int = MAX_LOG_LINE_LENGTH) -> str:
    """Truncate a value's string representation to max_len characters."""
    s = str(value)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


class ACPServerLogger:
    """Handles all logging for ACPServer with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance

    def server_starting(self) -> None:
        """Log server startup."""
        self._logger.info("=== Transactoid ACP Server Starting ===")

    def server_initialized(self) -> None:
        """Log server initialized."""
        self._logger.info("Server initialized, starting run loop...")

    def server_stopped(self) -> None:
        """Log server stopped."""
        self._logger.info("=== Transactoid ACP Server Stopped ===")

    def event_loop_starting(self) -> None:
        """Log event loop start."""
        self._logger.info("ACP server starting event loop")

    def request_dispatching(self, method: str, request_id: int | str | None) -> None:
        """Log request dispatch."""
        self._logger.bind(method=method, request_id=request_id).info(
            "Dispatching {} (id={})", method, request_id
        )

    def request_completed(self, method: str, request_id: int | str | None) -> None:
        """Log request completion."""
        self._logger.bind(method=method, request_id=request_id).info(
            "Handler completed for {} (id={})", method, request_id
        )

    def method_not_found(self, method: str) -> None:
        """Log method not found warning."""
        self._logger.bind(method=method).warning("Method not found: {}", method)

    def handler_error(self, method: str, error: Exception) -> None:
        """Log handler error with traceback."""
        self._logger.bind(method=method).exception(
            "Handler error for {}: {}", method, error
        )

    def stdin_closed(self) -> None:
        """Log stdin closure."""
        self._logger.info("stdin closed, shutting down")


class PromptHandlerLogger:
    """Handles all logging for PromptHandler with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance

    def prompt_received(self, session_id: str, param_keys: list[str]) -> None:
        """Log prompt request received."""
        self._logger.bind(session_id=session_id, param_keys=param_keys).info(
            "handle_prompt called with params keys: {}", param_keys
        )

    def prompt_details(self, session_id: str, content: list[dict[str, Any]]) -> None:
        """Log prompt details at debug level (truncated to 1000 chars)."""
        content_str = _truncate(content)
        self._logger.bind(session_id=session_id).debug(
            "session_id={}, content={}", session_id, content_str
        )

    def invalid_session(self, session_id: str) -> None:
        """Log invalid session warning."""
        self._logger.bind(session_id=session_id).warning(
            "Invalid session: {}", session_id
        )

    def no_text_content(self) -> None:
        """Log missing text content warning."""
        self._logger.warning("No text content in prompt")

    def user_prompt(self, session_id: str, text: str) -> None:
        """Log user prompt text (truncated to 100 chars)."""
        self._logger.bind(session_id=session_id).info("User prompt: {}", text[:100])

    def agent_stream_starting(self, session_id: str) -> None:
        """Log agent stream start."""
        self._logger.bind(session_id=session_id).info("Starting agent stream...")

    def event_received(self, event_count: int, event_type: str) -> None:
        """Log streaming event at debug level."""
        self._logger.bind(event_count=event_count, event_type=event_type).debug(
            "Event {}: type={}", event_count, event_type
        )

    def events_processed(self, session_id: str, event_count: int) -> None:
        """Log total events processed."""
        self._logger.bind(session_id=session_id, event_count=event_count).info(
            "Processed {} events from agent stream", event_count
        )

    def final_output(self, session_id: str, output: str) -> None:
        """Log final agent output (truncated to 100 chars)."""
        self._logger.bind(session_id=session_id).info("Final output: {}", output[:100])

    def returning_end_turn(self, session_id: str) -> None:
        """Log returning end_turn."""
        self._logger.bind(session_id=session_id).info(
            "handle_prompt returning end_turn"
        )

    def tool_call_started(self, name: str, call_id: str) -> None:
        """Log tool call started."""
        self._logger.bind(tool_name=name, call_id=call_id).info(
            "Tool call started: name={} call_id={}", name, call_id
        )

    def unhandled_event(self, event_type: str) -> None:
        """Log unhandled event type at debug level."""
        self._logger.bind(event_type=event_type).debug(
            "Unhandled event type: {}", event_type
        )

    def orphaned_tool_call(self, call_id: str, tool_name: str) -> None:
        """Log orphaned tool call that didn't complete."""
        self._logger.bind(call_id=call_id, tool_name=tool_name).warning(
            "Orphaned tool call: call_id={} tool_name={}", call_id, tool_name
        )
