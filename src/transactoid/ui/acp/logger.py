"""Logging for ACP server components.

Separates logging logic from business logic per AGENTS.md guidelines.
"""

from __future__ import annotations

from typing import Any

import loguru
from loguru import logger


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
        """Log prompt details at debug level."""
        self._logger.bind(session_id=session_id, content=content).debug(
            "session_id={}, content={}", session_id, content
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

    def processing_event(self, event_type: str, event_class: str) -> None:
        """Log event processing at debug level."""
        self._logger.bind(event_type=event_type, event_class=event_class).debug(
            "Processing event: type={}, event={}", event_type, event_class
        )

    def raw_response_no_data(self) -> None:
        """Log raw response with no data."""
        self._logger.debug("raw_response_event with no data, skipping")

    def raw_response_data_type(self, data_type: str) -> None:
        """Log raw response data type."""
        self._logger.bind(data_type=data_type).debug(
            "raw_response_event data.type={}", data_type
        )

    def tool_call_started(self, name: str, call_id: str) -> None:
        """Log tool call started."""
        self._logger.bind(tool_name=name, call_id=call_id).info(
            "Tool call started: name={} call_id={}", name, call_id
        )

    def output_item_done(self, call_id: str | None, item_type: str) -> None:
        """Log output item done at debug level."""
        self._logger.bind(call_id=call_id, item_type=item_type).debug(
            "output_item.done: call_id={} item.type={}", call_id, item_type
        )

    def run_item_stream_event(self, item_type: str, item: Any) -> None:
        """Log run item stream event."""
        self._logger.bind(item_type=item_type).info(
            "run_item_stream_event: item type={}, item={!r}", item_type, item
        )

    def tool_output(
        self, call_id: str, output_len: int, tracked: bool, tracked_ids: list[str]
    ) -> None:
        """Log tool output details."""
        self._logger.bind(
            call_id=call_id,
            output_len=output_len,
            tracked=tracked,
            tracked_ids=tracked_ids,
        ).info(
            "Tool output: call_id={} output_len={} tracked={} tracked_ids={}",
            call_id,
            output_len,
            tracked,
            tracked_ids,
        )

    def tool_output_text(self, text: str) -> None:
        """Log tool output text (truncated to 500 chars)."""
        self._logger.info("Tool output text: {}", text[:500])

    def tool_output_unknown(self, call_id: str, tracked_ids: list[str]) -> None:
        """Log warning for unknown tool call output."""
        self._logger.bind(call_id=call_id, tracked_ids=tracked_ids).warning(
            "Tool output for unknown call_id={}, tracked_ids={}, skipping",
            call_id,
            tracked_ids,
        )

    def non_tool_output_item(self, item_type: str) -> None:
        """Log non-ToolCallOutputItem at debug level."""
        self._logger.bind(item_type=item_type).debug(
            "run_item_stream_event with non-ToolCallOutputItem: {}", item_type
        )

    def unhandled_event(self, event_type: str) -> None:
        """Log unhandled event type at debug level."""
        self._logger.bind(event_type=event_type).debug(
            "Unhandled event type: {}", event_type
        )
