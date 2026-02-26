from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
import json
from typing import Literal, Protocol, TypeAlias, TypedDict, cast

from langchain_core.runnables import RunnableConfig

from transactoid.core.runtime.config import CoreRuntimeConfig
from transactoid.core.runtime.protocol import (
    CoreEvent,
    CoreRunResult,
    CoreRuntime,
    CoreSession,
    TextDeltaEvent,
    ToolCallArgsDeltaEvent,
    ToolCallCompletedEvent,
    ToolCallInputEvent,
    ToolCallOutputEvent,
    ToolCallRecord,
    ToolCallStartedEvent,
    ToolOutputEvent,
    TurnCompletedEvent,
    classify_tool_kind,
)
from transactoid.core.runtime.shared_tool_invoker import SharedToolInvoker
from transactoid.core.runtime.skills.paths import resolve_skill_paths
from transactoid.core.runtime.tool_adapters.langgraph import LangGraphToolAdapter
from transactoid.tools.registry import ToolRegistry


class _ThreadConfig(TypedDict):
    thread_id: str


class _NativeSessionConfig(TypedDict, total=False):
    configurable: _ThreadConfig
    recursion_limit: int


class _InputMessage(TypedDict):
    role: str
    content: str


class _AgentInput(TypedDict):
    messages: list[_InputMessage]


class _ToolCallChunk(TypedDict, total=False):
    id: str
    index: int
    name: str
    args: str


class _ToolCall(TypedDict, total=False):
    id: str
    name: str
    args: dict[str, object]


_ToolOutput: TypeAlias = dict[str, object] | str  # noqa: UP040


class _LangGraphAgentProtocol(Protocol):
    async def ainvoke(
        self,
        input: _AgentInput,
        config: RunnableConfig,
    ) -> dict[str, object]: ...

    def astream(
        self,
        input: _AgentInput,
        config: RunnableConfig,
        stream_mode: str,
    ) -> AsyncIterator[object]: ...


class LangGraphCoreRuntime(CoreRuntime):
    """Core runtime backed by LangGraph Deep Agents."""

    def __init__(
        self,
        *,
        instructions: str,
        registry: ToolRegistry,
        config: CoreRuntimeConfig,
    ) -> None:
        from deepagents import create_deep_agent
        from deepagents.backends.local_shell import LocalShellBackend
        from langgraph.checkpoint.memory import MemorySaver

        self._registry = registry
        self._invoker = SharedToolInvoker(registry)
        adapted_tools = LangGraphToolAdapter(
            registry=registry, invoker=self._invoker
        ).adapt_all()

        skill_paths = resolve_skill_paths(
            project_dir=config.skills_project_dir,
            user_dir=config.skills_user_dir,
            builtin_dir=config.skills_builtin_dir,
        )
        skill_dirs = [str(p) for p in skill_paths.all_existing()]

        backend = LocalShellBackend(root_dir=".")
        checkpointer = MemorySaver()

        self._agent: _LangGraphAgentProtocol = cast(
            _LangGraphAgentProtocol,
            create_deep_agent(
                model=config.model,
                tools=adapted_tools,
                system_prompt=instructions,
                backend=backend,
                skills=skill_dirs if skill_dirs else None,
                checkpointer=checkpointer,
            ),
        )

    def start_session(self, session_key: str) -> CoreSession:
        config: _NativeSessionConfig = {"configurable": {"thread_id": session_key}}
        return CoreSession(session_id=session_key, native_session=config)

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        run_config = self._build_run_config(session=session, max_turns=max_turns)
        result: dict[str, object] = await self._agent.ainvoke(
            self._build_input_payload(input_text),
            config=run_config,
        )

        final_text = self._extract_final_text(result)
        tool_calls = self._extract_tool_calls(result)
        return CoreRunResult(
            final_text=final_text,
            tool_calls=tool_calls,
            raw_metadata={},
        )

    def run_streamed(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        return self._iter_stream_events(input_text=input_text, session=session)

    async def close(self) -> None:
        return None

    async def _iter_stream_events(
        self,
        *,
        input_text: str,
        session: CoreSession,
    ) -> AsyncIterator[CoreEvent]:
        run_config = self._build_run_config(session=session, max_turns=None)
        accumulated_text = ""
        fallback_final_text = ""
        seen_tool_names: dict[str, str] = {}
        started_call_ids: set[str] = set()
        pending_started_ids: list[str] = []

        async for chunk in self._agent.astream(
            self._build_input_payload(input_text),
            config=run_config,
            stream_mode="messages",
        ):
            # astream stream_mode="messages" yields (message_chunk, metadata) tuples
            parsed_chunk = self._parse_stream_chunk(chunk)
            if parsed_chunk is None:
                continue
            message, _metadata = parsed_chunk

            # Text delta only from AI messages (not tool messages)
            msg_type = getattr(message, "type", None)
            content = getattr(message, "content", None)
            if msg_type != "tool":
                text_delta = self._extract_text_content(content)
                if text_delta:
                    fallback_final_text = text_delta
                    accumulated_text += text_delta
                    yield TextDeltaEvent(text=text_delta)

            # Tool call chunks from AIMessageChunk
            tool_call_chunks = self._extract_tool_call_chunks(message)
            for tc_chunk in tool_call_chunks:
                chunk_id = tc_chunk.get("id")
                chunk_index = tc_chunk.get("index", 0)
                call_id = (
                    str(chunk_id)
                    if isinstance(chunk_id, str) and chunk_id
                    else f"call_{chunk_index}"
                )
                chunk_name = tc_chunk.get("name")
                tool_name = chunk_name if isinstance(chunk_name, str) else ""
                chunk_args = tc_chunk.get("args")
                args_delta = chunk_args if isinstance(chunk_args, str) else ""

                if tool_name:
                    seen_tool_names[call_id] = tool_name
                    if call_id not in started_call_ids:
                        started_call_ids.add(call_id)
                        pending_started_ids.append(call_id)
                        yield ToolCallStartedEvent(
                            call_id=call_id,
                            tool_name=tool_name,
                            kind=classify_tool_kind(tool_name),
                        )
                if args_delta:
                    yield ToolCallArgsDeltaEvent(call_id=call_id, delta=args_delta)

            # Some providers populate `tool_calls` only on full AI messages.
            tool_calls = self._extract_tool_calls_from_message(message)
            for tc in tool_calls:
                tool_id = tc.get("id")
                tool_name_raw = tc.get("name")
                call_id = tool_id if isinstance(tool_id, str) and tool_id else "unknown"
                tool_name = (
                    tool_name_raw
                    if isinstance(tool_name_raw, str) and tool_name_raw
                    else ""
                )
                if tool_name:
                    seen_tool_names[call_id] = tool_name
                if call_id not in started_call_ids and tool_name:
                    started_call_ids.add(call_id)
                    pending_started_ids.append(call_id)
                    yield ToolCallStartedEvent(
                        call_id=call_id,
                        tool_name=tool_name,
                        kind=classify_tool_kind(tool_name),
                    )

            # Tool result from ToolMessage
            if msg_type == "tool":
                raw_call_id = getattr(message, "tool_call_id", "unknown")
                call_id = self._normalize_call_id(raw_call_id)
                raw_content = getattr(message, "content", "")
                output = self._parse_tool_output(raw_content)

                tool_name_for_call = seen_tool_names.get(call_id, "")
                if not tool_name_for_call:
                    message_tool_name = getattr(message, "name", None)
                    if isinstance(message_tool_name, str):
                        tool_name_for_call = message_tool_name
                if not tool_name_for_call and pending_started_ids:
                    pending_id = pending_started_ids[0]
                    tool_name_for_call = seen_tool_names.get(pending_id, "")
                    if tool_name_for_call:
                        seen_tool_names[call_id] = tool_name_for_call

                if call_id in pending_started_ids:
                    pending_started_ids.remove(call_id)
                elif pending_started_ids and tool_name_for_call:
                    pending_started_ids.pop(0)
                status = self._derive_tool_status(output)

                yield ToolCallInputEvent(
                    call_id=call_id,
                    tool_name=tool_name_for_call,
                    arguments={},
                    runtime_info=None,
                )
                yield ToolCallCompletedEvent(call_id=call_id)
                yield ToolOutputEvent(call_id=call_id, output=output)
                yield ToolCallOutputEvent(
                    call_id=call_id,
                    status=status,
                    output=output,
                    runtime_info=None,
                    named_outputs=None,
                )

        final_text = accumulated_text or fallback_final_text
        yield TurnCompletedEvent(final_text=final_text)

    def _extract_final_text(self, result: Mapping[str, object]) -> str:
        messages_raw = result.get("messages", [])
        messages = messages_raw if isinstance(messages_raw, list) else []
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai":
                content = getattr(msg, "content", "")
                final_text = self._extract_text_content(content)
                if final_text:
                    return final_text
        return ""

    def _extract_text_content(self, content: object) -> str:
        """Extract user-visible text from LangChain message content variants."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
                        continue
                    content_value = item.get("content")
                    if isinstance(content_value, str):
                        parts.append(content_value)
                        continue
                text_attr = getattr(item, "text", None)
                if isinstance(text_attr, str):
                    parts.append(text_attr)
            return "".join(parts)
        return ""

    def _extract_tool_calls(self, result: Mapping[str, object]) -> list[ToolCallRecord]:
        messages_raw = result.get("messages", [])
        messages = messages_raw if isinstance(messages_raw, list) else []
        calls: list[ToolCallRecord] = []

        pending: dict[str, tuple[str, dict[str, object]]] = {}
        for msg in messages:
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai":
                for tc in self._extract_tool_calls_from_message(msg):
                    call_id = self._normalize_call_id(tc.get("id"))
                    name = tc.get("name", "")
                    args = tc.get("args", {})
                    pending[call_id] = (name, args)
            elif msg_type == "tool":
                call_id = self._normalize_call_id(
                    getattr(msg, "tool_call_id", "unknown")
                )
                raw_content = getattr(msg, "content", "")
                output = self._parse_tool_output(raw_content)

                tool_name, arguments = pending.pop(call_id, ("", {}))
                status = self._derive_tool_status(output)
                calls.append(
                    ToolCallRecord(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        output=output,
                        status=status,
                    )
                )

        return calls

    def _build_input_payload(self, input_text: str) -> _AgentInput:
        return {"messages": [{"role": "user", "content": input_text}]}

    def _build_run_config(
        self,
        *,
        session: CoreSession,
        max_turns: int | None,
    ) -> RunnableConfig:
        native_session = session.native_session
        if not isinstance(native_session, dict):
            raise TypeError("LangGraph session.native_session must be a dict")

        base_config: _NativeSessionConfig = cast(
            _NativeSessionConfig,
            dict(native_session),
        )
        if max_turns is not None:
            base_config["recursion_limit"] = max_turns * 2
        return cast(RunnableConfig, base_config)

    def _parse_stream_chunk(self, chunk: object) -> tuple[object, object] | None:
        if not isinstance(chunk, tuple) or len(chunk) != 2:
            return None
        return (chunk[0], chunk[1])

    def _extract_tool_call_chunks(self, message: object) -> list[_ToolCallChunk]:
        chunks_raw = getattr(message, "tool_call_chunks", None)
        if not isinstance(chunks_raw, list):
            return []
        chunks: list[_ToolCallChunk] = []
        for chunk in chunks_raw:
            if isinstance(chunk, dict):
                normalized: _ToolCallChunk = {}
                chunk_id = chunk.get("id")
                if isinstance(chunk_id, str):
                    normalized["id"] = chunk_id
                chunk_index = chunk.get("index")
                if isinstance(chunk_index, int):
                    normalized["index"] = chunk_index
                chunk_name = chunk.get("name")
                if isinstance(chunk_name, str):
                    normalized["name"] = chunk_name
                chunk_args = chunk.get("args")
                if isinstance(chunk_args, str):
                    normalized["args"] = chunk_args
                chunks.append(normalized)
        return chunks

    def _extract_tool_calls_from_message(self, message: object) -> list[_ToolCall]:
        calls_raw = getattr(message, "tool_calls", None)
        if not isinstance(calls_raw, list):
            return []
        calls: list[_ToolCall] = []
        for call in calls_raw:
            if isinstance(call, dict):
                normalized: _ToolCall = {}
                call_id = call.get("id")
                if isinstance(call_id, str):
                    normalized["id"] = call_id
                call_name = call.get("name")
                if isinstance(call_name, str):
                    normalized["name"] = call_name
                call_args = call.get("args")
                if isinstance(call_args, dict):
                    normalized["args"] = cast(dict[str, object], call_args)
                calls.append(normalized)
        return calls

    def _normalize_call_id(self, raw_call_id: object) -> str:
        if isinstance(raw_call_id, str) and raw_call_id:
            return raw_call_id
        return "unknown"

    def _parse_tool_output(self, raw_content: object) -> _ToolOutput:
        content_text = raw_content if isinstance(raw_content, str) else str(raw_content)
        try:
            parsed = json.loads(content_text)
        except (TypeError, ValueError):
            return content_text
        return parsed if isinstance(parsed, dict) else content_text

    def _derive_tool_status(
        self,
        output: _ToolOutput,
    ) -> Literal["completed", "failed"]:
        if isinstance(output, dict) and output.get("status") == "error":
            return "failed"
        return "completed"
