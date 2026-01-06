"""Route JSON-RPC requests to handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Handler type: async function that takes params dict and returns result dict
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class MethodNotFoundError(Exception):
    """Raised when a method is not registered with the router."""

    def __init__(self, method: str) -> None:
        self.method = method
        super().__init__(f"Method not found: {method}")


class RequestRouter:
    """Route JSON-RPC methods to handlers.

    Maps method names (e.g., 'initialize', 'session/new') to async handler
    functions. Handlers receive the params dict and return a result dict.

    Example:
        router = RequestRouter()

        async def handle_ping(params: dict[str, Any]) -> dict[str, Any]:
            return {"pong": True}

        router.register("ping", handle_ping)
        result = await router.dispatch("ping", {})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        """Register handler for a JSON-RPC method.

        Args:
            method: The method name (e.g., 'initialize', 'session/new')
            handler: Async function that takes params and returns result
        """
        self._handlers[method] = handler

    async def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch request to registered handler.

        Args:
            method: The method name to dispatch to
            params: The params dict from the JSON-RPC request

        Returns:
            The result dict from the handler

        Raises:
            MethodNotFoundError: If no handler is registered for the method
        """
        handler = self._handlers.get(method)
        if handler is None:
            raise MethodNotFoundError(method)
        return await handler(params)

    def has_method(self, method: str) -> bool:
        """Check if a handler is registered for the method."""
        return method in self._handlers

    @property
    def methods(self) -> list[str]:
        """List all registered method names."""
        return list(self._handlers.keys())
