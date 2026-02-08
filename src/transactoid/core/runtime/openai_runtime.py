from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any, Literal, cast

from agents import Agent, ModelSettings, Runner, SQLiteSession, WebSearchTool
from agents.items import ToolCallOutputItem
from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent
from openai.types.shared import Reasoning

from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.protocol import (
    CoreEvent,
    CoreRunResult,
    CoreRuntime,
    CoreSession,
    TextDeltaEvent,
    ThoughtDeltaEvent,
    ToolCallArgsDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallRecord,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
    classify_tool_kind,
)
from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.core.runtime.tool_adapters.openai import OpenAIToolAdapter
from transactoid.tools.registry import ToolRegistry


class OpenAICoreRuntime(CoreRuntime):
    """Core runtime backed by OpenAI Agents SDK."""

    def __init__(
        self,
        *,
        instructions: str,
        registry: ToolRegistry,
        config: CoreRuntimeConfig,
    ) -> None:
        self._registry = registry
        self._invoker = SharedToolInvoker(registry)
        tools: list[Any] = OpenAIToolAdapter(
            registry=registry, invoker=self._invoker
        ).adapt_all()
        if config.enable_web_search:
            tools.append(WebSearchTool())

        self._agent = Agent(
            name="Transactoid",
            instructions=instructions,
            model=config.model,
            tools=tools,
            model_settings=ModelSettings(
                reasoning=Reasoning(effort=config.reasoning_effort, summary="auto"),
                verbosity=config.verbosity,
            ),
        )

    @property
    def native_agent(self) -> object:
        """Expose underlying OpenAI Agent for backward-compatible call sites."""
        return self._agent

    def start_session(self, session_key: str) -> CoreSession:
        return CoreSession(
            session_id=session_key, native_session=SQLiteSession(session_key)
        )

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        kwargs: dict[str, Any] = {
            "input": input_text,
            "session": session.native_session,
        }
        if max_turns is not None:
            kwargs["max_turns"] = max_turns

        result = await Runner.run(self._agent, **kwargs)
        final_text = self._extract_final_text(result)
        tool_calls = self._extract_tool_calls(result)
        return CoreRunResult(
            final_text=final_text,
            tool_calls=tool_calls,
            raw_metadata={},
        )

    async def close(self) -> None:
        return None

    async def _iter_stream_events(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        stream = Runner.run_streamed(
            self._agent,
            input_text,
            session=cast(Any, session.native_session),
        )
        last_call_id: str | None = None

        async for event in stream.stream_events():
            event_type = getattr(event, "type", "")

            if event_type == "raw_response_event":
                data = getattr(event, "data", None)
                if data is None:
                    continue

                data_type = getattr(data, "type", "")

                if data_type == "response.output_text.delta":
                    delta = getattr(data, "delta", None)
                    if delta:
                        yield TextDeltaEvent(text=delta)
                    continue

                if data_type == "response.reasoning_summary_text.delta":
                    delta = getattr(data, "delta", None)
                    if delta:
                        yield ThoughtDeltaEvent(text=delta)
                    continue

                if isinstance(data, ResponseFunctionCallArgumentsDeltaEvent):
                    call_id = (
                        getattr(data, "call_id", None) or last_call_id or "unknown"
                    )
                    delta = getattr(data, "delta", "")
                    if delta:
                        yield ToolCallArgsDeltaEvent(call_id=call_id, delta=delta)
                    continue

                item = getattr(data, "item", None)
                if (
                    data_type == "response.output_item.added"
                    and getattr(item, "type", "") == "function_call"
                ):
                    tool_name = getattr(item, "name", "unknown")
                    call_id = getattr(item, "call_id", "unknown")
                    last_call_id = call_id
                    yield ToolCallStartedEvent(
                        call_id=call_id,
                        tool_name=tool_name,
                        kind=classify_tool_kind(tool_name),
                    )
                    continue

                if data_type == "response.output_item.done":
                    call_id = getattr(item, "call_id", None)
                    if call_id:
                        yield ToolCallCompletedEvent(call_id=call_id)
                        if last_call_id == call_id:
                            last_call_id = None
                    continue

            if event_type == "run_item_stream_event":
                item = getattr(event, "item", None)
                if not isinstance(item, ToolCallOutputItem):
                    continue
                raw_item = getattr(item, "raw_item", None)
                call_id = getattr(raw_item, "call_id", None) if raw_item else None
                if call_id is None and isinstance(raw_item, dict):
                    call_id = raw_item.get("call_id")
                if call_id is None:
                    call_id = "unknown"
                output = item.output
                normalized_output = (
                    output if isinstance(output, dict | str) else str(output)
                )
                yield ToolOutputEvent(call_id=call_id, output=normalized_output)

        get_final_result = getattr(stream, "get_final_result", None)
        final_text = ""
        if callable(get_final_result):
            final_text = self._extract_final_text(get_final_result())
        yield TurnCompletedEvent(final_text=final_text)

    def run_streamed(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        return self._iter_stream_events(input_text=input_text, session=session)

    def _extract_final_text(self, result: Any) -> str:
        final_output = getattr(result, "final_output", None)
        if isinstance(final_output, str):
            return final_output
        if final_output is not None and hasattr(final_output, "text"):
            return str(final_output.text)
        return ""

    def _extract_tool_calls(self, result: Any) -> list[ToolCallRecord]:
        calls: list[ToolCallRecord] = []
        for item in getattr(result, "new_items", []):
            if not isinstance(item, ToolCallOutputItem):
                continue

            raw_item = getattr(item, "raw_item", None)
            call_id = getattr(raw_item, "call_id", None) if raw_item else None
            if call_id is None and isinstance(raw_item, dict):
                call_id = raw_item.get("call_id")
            call_id = call_id or "unknown"

            tool_name = ""
            if raw_item is not None:
                tool_name = getattr(raw_item, "name", "") or ""
            if not tool_name:
                tool_name = self._infer_tool_name(item.output)

            arguments: dict[str, Any] = {}
            if raw_item is not None:
                args_json = getattr(raw_item, "arguments", None)
                if isinstance(args_json, str):
                    try:
                        decoded_args = json.loads(args_json)
                        if isinstance(decoded_args, dict):
                            arguments = decoded_args
                    except json.JSONDecodeError:
                        arguments = {}

            output = item.output
            normalized_output = (
                output if isinstance(output, dict | str) else str(output)
            )
            status: Literal["completed", "failed"] = "failed"
            if isinstance(output, dict) and output.get("status") != "error":
                status = "completed"
            elif not isinstance(output, dict):
                status = "completed"

            calls.append(
                ToolCallRecord(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    output=normalized_output,
                    status=status,
                )
            )
        return calls

    def _infer_tool_name(self, output: Any) -> str:
        if not isinstance(output, dict):
            return ""

        keys = set(output.keys())
        if "rows" in keys and "count" in keys:
            return "run_sql"
        if "accounts" in keys and "status" in keys:
            return "list_accounts"
        if "pages_processed" in keys or "items_synced" in keys:
            return "sync_transactions"
        if "status" in keys and "item_id" in keys:
            return "connect_new_account"
        if "updated" in keys and "error" in keys:
            return "recategorize_merchant"
        if "applied" in keys and "created_tags" in keys:
            return "tag_transactions"
        return ""
