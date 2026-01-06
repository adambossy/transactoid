"""Tests for ACP request router."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from transactoid.ui.acp.router import (
    Handler,
    MethodNotFoundError,
    RequestRouter,
)


class TestRequestRouter:
    """Tests for RequestRouter class."""

    def test_register_adds_handler(self) -> None:
        router = RequestRouter()

        async def handler(params: dict[str, Any]) -> dict[str, Any]:
            return {}

        router.register("test", handler)

        assert router.has_method("test")

    def test_has_method_returns_false_for_unregistered(self) -> None:
        router = RequestRouter()

        assert not router.has_method("nonexistent")

    def test_methods_returns_registered_method_names(self) -> None:
        router = RequestRouter()

        async def handler(params: dict[str, Any]) -> dict[str, Any]:
            return {}

        router.register("initialize", handler)
        router.register("session/new", handler)
        router.register("session/prompt", handler)

        assert sorted(router.methods) == ["initialize", "session/new", "session/prompt"]

    def test_methods_returns_empty_list_initially(self) -> None:
        router = RequestRouter()

        assert router.methods == []

    def test_dispatch_calls_registered_handler(self) -> None:
        router = RequestRouter()
        params = {"version": 1}

        async def handler(p: dict[str, Any]) -> dict[str, Any]:
            return {"result": "success", "received": p}

        router.register("test", handler)

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("test", params)

        result = asyncio.run(run_test())

        assert result["result"] == "success"
        assert result["received"] == params

    def test_dispatch_raises_method_not_found_for_unregistered(self) -> None:
        router = RequestRouter()

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("nonexistent", {})

        with pytest.raises(MethodNotFoundError, match="Method not found: nonexistent"):
            asyncio.run(run_test())

    def test_dispatch_passes_empty_params(self) -> None:
        router = RequestRouter()
        received_params: list[dict[str, Any]] = []

        async def handler(params: dict[str, Any]) -> dict[str, Any]:
            received_params.append(params)
            return {}

        router.register("ping", handler)

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("ping", {})

        asyncio.run(run_test())

        assert received_params == [{}]

    def test_dispatch_preserves_handler_exception(self) -> None:
        router = RequestRouter()

        async def failing_handler(params: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("Handler error")

        router.register("fail", failing_handler)

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("fail", {})

        with pytest.raises(ValueError, match="Handler error"):
            asyncio.run(run_test())

    def test_register_overwrites_existing_handler(self) -> None:
        router = RequestRouter()

        async def handler1(params: dict[str, Any]) -> dict[str, Any]:
            return {"version": 1}

        async def handler2(params: dict[str, Any]) -> dict[str, Any]:
            return {"version": 2}

        router.register("test", handler1)
        router.register("test", handler2)

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("test", {})

        result = asyncio.run(run_test())

        assert result == {"version": 2}

    def test_dispatch_with_nested_params(self) -> None:
        router = RequestRouter()
        params = {
            "sessionId": "sess_abc123",
            "content": [{"type": "text", "text": "Hello"}],
            "options": {"streaming": True},
        }

        async def handler(p: dict[str, Any]) -> dict[str, Any]:
            return {"echo": p}

        router.register("session/prompt", handler)

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("session/prompt", params)

        result = asyncio.run(run_test())

        assert result["echo"] == params

    def test_multiple_handlers_dispatch_correctly(self) -> None:
        router = RequestRouter()

        async def init_handler(params: dict[str, Any]) -> dict[str, Any]:
            return {"type": "init", "version": params.get("version", 1)}

        async def session_handler(params: dict[str, Any]) -> dict[str, Any]:
            return {"type": "session", "id": "sess_123"}

        async def prompt_handler(params: dict[str, Any]) -> dict[str, Any]:
            return {"type": "prompt", "response": "Hello"}

        router.register("initialize", init_handler)
        router.register("session/new", session_handler)
        router.register("session/prompt", prompt_handler)

        async def run_test() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            r1 = await router.dispatch("initialize", {"version": 2})
            r2 = await router.dispatch("session/new", {})
            r3 = await router.dispatch("session/prompt", {})
            return r1, r2, r3

        r1, r2, r3 = asyncio.run(run_test())

        assert r1 == {"type": "init", "version": 2}
        assert r2 == {"type": "session", "id": "sess_123"}
        assert r3 == {"type": "prompt", "response": "Hello"}


class TestMethodNotFoundError:
    """Tests for MethodNotFoundError exception."""

    def test_error_message_includes_method_name(self) -> None:
        error = MethodNotFoundError("session/unknown")

        assert str(error) == "Method not found: session/unknown"

    def test_error_stores_method_attribute(self) -> None:
        error = MethodNotFoundError("test/method")

        assert error.method == "test/method"

    def test_error_is_exception(self) -> None:
        assert issubclass(MethodNotFoundError, Exception)


class TestHandlerType:
    """Tests to verify Handler type alias works correctly."""

    def test_handler_type_accepts_async_function(self) -> None:
        async def my_handler(params: dict[str, Any]) -> dict[str, Any]:
            return {"status": "ok"}

        # Type-check at runtime that it's callable
        handler: Handler = my_handler
        assert callable(handler)

    def test_handler_type_accepts_lambda_style_async(self) -> None:
        router = RequestRouter()

        # Using a class with __call__ as handler
        class CallableHandler:
            async def __call__(self, params: dict[str, Any]) -> dict[str, Any]:
                return {"class": True}

        router.register("class_handler", CallableHandler())

        async def run_test() -> dict[str, Any]:
            return await router.dispatch("class_handler", {})

        result = asyncio.run(run_test())

        assert result == {"class": True}
