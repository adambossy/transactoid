"""Prompt processing handler for ACP protocol.

Handles 'session/prompt' requests by running the agent and streaming
responses back to the client via session/update notifications.
"""

from __future__ import annotations

import logging
from typing import Any

from agents import Agent, Runner, SQLiteSession
from agents.items import ToolCallOutputItem
from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent

from transactoid.ui.acp.handlers.session import SessionManager
from transactoid.ui.acp.notifier import ToolCallKind, UpdateNotifier

logger = logging.getLogger(__name__)


class PromptHandler:
    """Handle session/prompt requests by running the agent.

    Processes user prompts through the Transactoid agent and streams
    responses back via the UpdateNotifier. Translates OpenAI Agents SDK
    streaming events into ACP session/update notifications.

    Example:
        handler = PromptHandler(
            session_manager=sessions,
            agent=transactoid.create_agent(),
            notifier=notifier,
        )
        result = await handler.handle_prompt({
            "sessionId": "sess_abc123",
            "content": [{"type": "text", "text": "How much did I spend?"}],
        })
    """

    def __init__(
        self,
        session_manager: SessionManager,
        agent: Agent,
        notifier: UpdateNotifier,
    ) -> None:
        """Initialize the prompt handler.

        Args:
            session_manager: SessionManager for session lookup
            agent: Configured Agent instance for processing prompts
            notifier: UpdateNotifier for sending session updates
        """
        self._sessions = session_manager
        self._agent = agent
        self._notifier = notifier
        # Track tool call states for args accumulation
        self._tool_calls: dict[str, _ToolCallState] = {}
        # Track the latest call_id for SDKs that don't provide it on every delta
        self._last_call_id: str | None = None

    async def handle_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Process a user prompt and stream responses.

        Extracts the user message from content blocks, runs it through
        the agent, and streams tool calls and message deltas as
        session/update notifications.

        Args:
            params: Request parameters containing:
                - sessionId: The session to run the prompt in
                - content: List of content blocks (text, image, etc.)

        Returns:
            Response dict containing:
                - stopReason: Why the agent stopped (e.g., "end_turn")
                Or error dict if session is invalid
        """
        logger.info("handle_prompt called with params keys: %s", list(params.keys()))
        session_id = params.get("sessionId", "")
        content: list[dict[str, Any]] = params.get("content", [])
        logger.debug("session_id=%s, content=%s", session_id, content)

        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("Invalid session: %s", session_id)
            return {"error": {"code": -32600, "message": "Invalid session"}}

        # Extract text from content blocks
        user_text = ""
        for block in content:
            if block.get("type") == "text":
                text_value = block.get("text")
                if isinstance(text_value, str):
                    user_text = text_value
                    break

        if not user_text:
            logger.warning("No text content in prompt")
            return {"error": {"code": -32602, "message": "No text content provided"}}

        logger.info("User prompt: %s", user_text[:100])

        # Add user message to session history
        self._sessions.add_message(session_id, {"role": "user", "content": user_text})

        # Create SDK session for memory persistence
        sdk_session = SQLiteSession(session_id)

        # Run agent with streaming
        logger.info("Starting agent stream...")
        stream = Runner.run_streamed(
            self._agent,
            user_text,
            session=sdk_session,
        )

        # Process streaming events
        event_count = 0
        async for event in stream.stream_events():
            event_count += 1
            logger.debug("Event %d: type=%s", event_count, getattr(event, "type", "?"))
            await self._process_event(session_id, event)

        logger.info("Processed %d events from agent stream", event_count)

        # Add assistant response to session history (if available)
        get_final_result = getattr(stream, "get_final_result", None)
        if callable(get_final_result):
            final_result = get_final_result()
            final_output = getattr(final_result, "final_output", None)
            if final_output:
                logger.info("Final output: %s", str(final_output)[:100])
                self._sessions.add_message(
                    session_id,
                    {"role": "assistant", "content": str(final_output)},
                )

        logger.info("handle_prompt returning end_turn")
        return {"stopReason": "end_turn"}

    async def _process_event(self, session_id: str, event: Any) -> None:
        """Convert an agent streaming event to ACP notifications.

        Translates OpenAI Agents SDK events into the appropriate
        session/update notification types.

        Args:
            session_id: The session to send updates for
            event: Streaming event from the agent runner
        """
        et = getattr(event, "type", "")

        # Handle raw response events
        if et == "raw_response_event":
            data = getattr(event, "data", None)
            if data is None:
                return

            dt = getattr(data, "type", "")

            # Output text -> agent_message_chunk
            if dt == "response.output_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    await self._notifier.agent_message_chunk(
                        session_id=session_id,
                        content={"type": "text", "text": delta},
                    )
                return

            # Reasoning text -> agent_thought_chunk
            if dt == "response.reasoning_summary_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    await self._notifier.agent_thought_chunk(
                        session_id=session_id,
                        content={"type": "thinking", "text": delta},
                    )
                return

            # Function call arguments delta
            if isinstance(data, ResponseFunctionCallArgumentsDeltaEvent):
                call_id = (
                    getattr(data, "call_id", None) or self._last_call_id or "unknown"
                )
                state = self._tool_calls.get(call_id)
                if state:
                    state.args_chunks.append(data.delta or "")
                return

            # Function call started
            item = getattr(data, "item", None)
            if (
                dt == "response.output_item.added"
                and getattr(item, "type", "") == "function_call"
            ):
                name = getattr(item, "name", "unknown")
                call_id = getattr(item, "call_id", "unknown")
                self._last_call_id = call_id

                # Track the tool call state
                self._tool_calls[call_id] = _ToolCallState(call_id, name)

                # Send pending notification
                await self._notifier.tool_call(
                    session_id=session_id,
                    tool_call_id=call_id,
                    title=name,
                    kind=self._get_kind(name),
                    status="pending",
                )
                return

            # Function call completed (arguments done)
            if dt == "response.output_item.done":
                call_id = getattr(item, "call_id", None)
                if call_id:
                    # Send in_progress notification
                    await self._notifier.tool_call_update(
                        session_id=session_id,
                        tool_call_id=call_id,
                        status="in_progress",
                    )
                    if self._last_call_id == call_id:
                        self._last_call_id = None
                return

        # Handle run item events (tool execution results)
        if et == "run_item_stream_event":
            item = getattr(event, "item", None)
            if isinstance(item, ToolCallOutputItem):
                call_id = getattr(item, "call_id", None) or "unknown"
                output = item.output
                output_text = str(output) if output is not None else ""

                # Send completed notification with output
                await self._notifier.tool_call_update(
                    session_id=session_id,
                    tool_call_id=call_id,
                    status="completed",
                    content=[{"type": "text", "text": output_text}],
                )

                # Clean up tool call state
                self._tool_calls.pop(call_id, None)
                return

    def _get_kind(self, tool_name: str) -> ToolCallKind:
        """Map tool name to ACP tool call kind.

        Args:
            tool_name: Name of the tool being called

        Returns:
            The ACP tool call kind classification
        """
        kind_map: dict[str, ToolCallKind] = {
            "sync_transactions": "fetch",
            "run_sql": "execute",
            "recategorize_merchant": "edit",
            "tag_transactions": "edit",
            "connect_new_account": "other",
            "list_accounts": "fetch",
            "update_category_for_transaction_groups": "edit",
        }
        return kind_map.get(tool_name, "other")


class _ToolCallState:
    """Track state for a streaming tool call."""

    def __init__(self, call_id: str, name: str) -> None:
        self.call_id = call_id
        self.name = name
        self.args_chunks: list[str] = []

    def args_text(self) -> str:
        """Get accumulated arguments as a single string."""
        return "".join(self.args_chunks)
