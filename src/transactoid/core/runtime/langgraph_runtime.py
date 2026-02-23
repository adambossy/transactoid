from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, cast

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

        self._agent = create_deep_agent(
            model=config.model,
            tools=adapted_tools,
            system_prompt=instructions,
            backend=backend,
            skills=skill_dirs if skill_dirs else None,
            checkpointer=checkpointer,
        )

    def start_session(self, session_key: str) -> CoreSession:
        config: dict[str, Any] = {"configurable": {"thread_id": session_key}}
        return CoreSession(session_id=session_key, native_session=config)

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        base_config = dict(cast(dict[str, Any], session.native_session))
        if max_turns is not None:
            base_config["recursion_limit"] = max_turns * 2
        run_config = cast(RunnableConfig, base_config)

        result: dict[str, Any] = await self._agent.ainvoke(
            {"messages": [{"role": "user", "content": input_text}]},
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
        run_config = cast(RunnableConfig, session.native_session)
        accumulated_text = ""
        seen_tool_names: dict[str, str] = {}

        async for chunk in self._agent.astream(
            {"messages": [{"role": "user", "content": input_text}]},
            config=run_config,
            stream_mode="messages",
        ):
            # astream stream_mode="messages" yields (message_chunk, metadata) tuples
            if not isinstance(chunk, tuple) or len(chunk) != 2:
                continue
            message, _metadata = chunk

            # Text delta only from AI messages (not tool messages)
            msg_type = getattr(message, "type", None)
            content = getattr(message, "content", None)
            if msg_type != "tool" and isinstance(content, str) and content:
                accumulated_text += content
                yield TextDeltaEvent(text=content)

            # Tool call chunks from AIMessageChunk
            tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
            for tc_chunk in tool_call_chunks:
                call_id: str = tc_chunk.get("id") or f"call_{tc_chunk.get('index', 0)}"
                tool_name: str = tc_chunk.get("name") or ""
                args_delta: str = tc_chunk.get("args") or ""

                if tool_name:
                    seen_tool_names[call_id] = tool_name
                    yield ToolCallStartedEvent(
                        call_id=call_id,
                        tool_name=tool_name,
                        kind=classify_tool_kind(tool_name),
                    )
                if args_delta:
                    yield ToolCallArgsDeltaEvent(call_id=call_id, delta=args_delta)

            # Tool result from ToolMessage
            if msg_type == "tool":
                call_id = getattr(message, "tool_call_id", "unknown") or "unknown"
                raw_content = getattr(message, "content", "")
                output: dict[str, object] | str
                try:
                    import json as _json

                    parsed = _json.loads(raw_content)
                    output = parsed if isinstance(parsed, dict) else raw_content
                except Exception:
                    output = (
                        raw_content
                        if isinstance(raw_content, str)
                        else str(raw_content)
                    )

                tool_name_for_call = seen_tool_names.get(call_id, "")
                status: Literal["completed", "failed"] = "completed"
                if isinstance(output, dict) and output.get("status") == "error":
                    status = "failed"

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

        yield TurnCompletedEvent(final_text=accumulated_text)

    def _extract_final_text(self, result: dict[str, Any]) -> str:
        messages: list[Any] = result.get("messages", [])
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai":
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    return content
        return ""

    def _extract_tool_calls(self, result: dict[str, Any]) -> list[ToolCallRecord]:
        import json as _json

        messages: list[Any] = result.get("messages", [])
        calls: list[ToolCallRecord] = []

        pending: dict[str, tuple[str, dict[str, object]]] = {}
        for msg in messages:
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai":
                for tc in getattr(msg, "tool_calls", []) or []:
                    call_id = tc.get("id", "unknown") or "unknown"
                    name = tc.get("name", "") or ""
                    args = tc.get("args", {}) or {}
                    pending[call_id] = (name, args if isinstance(args, dict) else {})
            elif msg_type == "tool":
                call_id = getattr(msg, "tool_call_id", "unknown") or "unknown"
                raw_content = getattr(msg, "content", "")
                output: dict[str, object] | str
                try:
                    parsed = _json.loads(raw_content)
                    output = parsed if isinstance(parsed, dict) else raw_content
                except Exception:
                    output = (
                        raw_content
                        if isinstance(raw_content, str)
                        else str(raw_content)
                    )

                tool_name, arguments = pending.pop(call_id, ("", {}))
                status: Literal["completed", "failed"] = "completed"
                if isinstance(output, dict) and output.get("status") == "error":
                    status = "failed"
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
