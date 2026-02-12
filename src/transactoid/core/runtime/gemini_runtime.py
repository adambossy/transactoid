from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

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
from transactoid.core.runtime.tool_adapters.gemini import GeminiToolAdapter
from transactoid.tools.registry import ToolRegistry


class GeminiCoreRuntime(CoreRuntime):
    """Core runtime backed by Google ADK and Gemini models."""

    def __init__(
        self,
        *,
        instructions: str,
        registry: ToolRegistry,
        config: CoreRuntimeConfig,
    ) -> None:
        self._registry = registry
        self._invoker = SharedToolInvoker(registry)
        self._tools = GeminiToolAdapter(
            registry=registry,
            invoker=self._invoker,
        ).adapt_all()

        session_service_factory: Any = InMemorySessionService
        self._session_service = session_service_factory()
        self._user_id = "transactoid"
        self._app_name = "transactoid"

        self._agent = LlmAgent(
            name="transactoid",
            description="Personal finance agent runtime",
            instruction=instructions,
            model=config.model,
            tools=list(self._tools),  # cast via list[Any]-compatible path
        )
        self._runner = Runner(
            app_name=self._app_name,
            agent=self._agent,
            session_service=self._session_service,
        )

    def start_session(self, session_key: str) -> CoreSession:
        existing_session = self._session_service.get_session_sync(
            app_name=self._app_name,
            user_id=self._user_id,
            session_id=session_key,
        )
        if existing_session is None:
            self._session_service.create_session_sync(
                app_name=self._app_name,
                user_id=self._user_id,
                session_id=session_key,
                state={},
            )
        return CoreSession(session_id=session_key, native_session=session_key)

    async def run(
        self,
        *,
        input_text: str,
        session: CoreSession,
        max_turns: int | None = None,
    ) -> CoreRunResult:
        _ = max_turns
        pending_calls: dict[str, tuple[str, dict[str, object]]] = {}
        tool_calls: list[ToolCallRecord] = []
        accumulated_text = ""
        fallback_final_text = ""

        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=session.session_id,
            new_message=self._build_user_message(input_text),
        ):
            content = getattr(event, "content", None)
            if content is not None:
                for part in getattr(content, "parts", []) or []:
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        call_id = getattr(function_call, "id", None) or (
                            f"call_{len(pending_calls) + len(tool_calls) + 1}"
                        )
                        name = str(getattr(function_call, "name", ""))
                        args_obj = getattr(function_call, "args", None)
                        args = args_obj if isinstance(args_obj, dict) else {}
                        pending_calls[call_id] = (name, args)

                    function_response = getattr(part, "function_response", None)
                    if function_response is not None:
                        call_id = getattr(function_response, "id", None) or (
                            f"call_{len(tool_calls) + 1}"
                        )
                        name = str(getattr(function_response, "name", ""))
                        response_obj = getattr(function_response, "response", None)
                        output: dict[str, object] | str
                        if isinstance(response_obj, dict):
                            output = response_obj
                        else:
                            output = str(response_obj)

                        pending_name, pending_args = pending_calls.pop(
                            call_id,
                            (name, {}),
                        )
                        status: Literal["completed", "failed"] = "completed"
                        if isinstance(output, dict) and output.get("status") == "error":
                            status = "failed"
                        tool_calls.append(
                            ToolCallRecord(
                                call_id=call_id,
                                tool_name=pending_name,
                                arguments=pending_args,
                                output=output,
                                status=status,
                            )
                        )

                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str):
                        fallback_final_text += part_text
                        if getattr(event, "partial", False):
                            accumulated_text += part_text

        final_text = accumulated_text or fallback_final_text
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
        accumulated_text = ""
        fallback_final_text = ""
        seen_partial_text = False
        tool_call_counter = 0

        async for event in self._runner.run_async(
            user_id=self._user_id,
            session_id=session.session_id,
            new_message=self._build_user_message(input_text),
        ):
            content = getattr(event, "content", None)
            if content is None:
                continue

            for part in getattr(content, "parts", []) or []:
                function_call = getattr(part, "function_call", None)
                if function_call is not None:
                    tool_call_counter += 1
                    call_id = getattr(function_call, "id", None) or (
                        f"call_{tool_call_counter}"
                    )
                    tool_name = str(getattr(function_call, "name", "unknown"))
                    args_obj = getattr(function_call, "args", None)
                    args = args_obj if isinstance(args_obj, dict) else {}
                    yield ToolCallStartedEvent(
                        call_id=call_id,
                        tool_name=tool_name,
                        kind=classify_tool_kind(tool_name),
                    )
                    args_json = json.dumps(args)
                    if args_json:
                        yield ToolCallArgsDeltaEvent(call_id=call_id, delta=args_json)

                function_response = getattr(part, "function_response", None)
                if function_response is not None:
                    call_id = getattr(function_response, "id", None) or (
                        f"call_{tool_call_counter}"
                    )
                    response_obj = getattr(function_response, "response", None)
                    output: dict[str, object] | str
                    if isinstance(response_obj, dict):
                        output = response_obj
                    else:
                        output = str(response_obj)
                    yield ToolCallCompletedEvent(call_id=call_id)
                    yield ToolOutputEvent(call_id=call_id, output=output)

                part_text = getattr(part, "text", None)
                if isinstance(part_text, str):
                    fallback_final_text = part_text
                    part_is_thought = bool(getattr(part, "thought", False))

                    if getattr(event, "partial", False):
                        seen_partial_text = True
                        if part_is_thought:
                            yield ThoughtDeltaEvent(text=part_text)
                        else:
                            yield TextDeltaEvent(text=part_text)
                            accumulated_text += part_text
                    elif not seen_partial_text:
                        if part_is_thought:
                            yield ThoughtDeltaEvent(text=part_text)
                        else:
                            yield TextDeltaEvent(text=part_text)
                            accumulated_text += part_text

        final_text = accumulated_text or fallback_final_text
        yield TurnCompletedEvent(final_text=final_text)

    def _build_user_message(self, input_text: str) -> Any:
        return genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=input_text)],
        )
