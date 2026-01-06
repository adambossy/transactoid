"""JSON-RPC transport over stdin/stdout for ACP server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import sys
from typing import Any

# Configure logger to write to stderr (stdout is for JSON-RPC)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonRpcRequest:
    """JSON-RPC 2.0 request message.

    Requests include an `id` and expect a response.
    """

    method: str
    id: int | str | None = None
    params: dict[str, Any] | None = None
    jsonrpc: str = field(default="2.0")


@dataclass(frozen=True)
class JsonRpcResponse:
    """JSON-RPC 2.0 response message.

    Sent in reply to a request with matching `id`.
    """

    id: int | str | None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    jsonrpc: str = field(default="2.0")


@dataclass(frozen=True)
class JsonRpcNotification:
    """JSON-RPC 2.0 notification message.

    Notifications have no `id` and expect no response.
    """

    method: str
    params: dict[str, Any] | None = None
    jsonrpc: str = field(default="2.0")


class StdioTransport:
    """Bidirectional JSON-RPC transport via stdin/stdout.

    Provides async methods for reading requests from stdin and
    writing responses/notifications to stdout. Each message is
    a single line of JSON.

    Uses run_in_executor for blocking stdin reads to avoid
    complications with async pipe setup on all platforms.
    """

    async def read_message(self) -> JsonRpcRequest:
        """Read next JSON-RPC request from stdin.

        Reads a single line, parses it as JSON, and constructs
        a JsonRpcRequest. Raises EOFError if stdin is closed,
        or JSONDecodeError if the line is not valid JSON.
        """
        loop = asyncio.get_running_loop()
        line: str = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            logger.debug("stdin closed (empty line)")
            raise EOFError("stdin closed")
        logger.debug("RECV: %s", line.strip()[:500])
        data: dict[str, Any] = json.loads(line)
        request = JsonRpcRequest(
            method=str(data.get("method", "")),
            id=data.get("id"),
            params=data.get("params"),
            jsonrpc=str(data.get("jsonrpc", "2.0")),
        )
        logger.info("← Request: method=%s id=%s", request.method, request.id)
        return request

    async def write_response(self, response: JsonRpcResponse) -> None:
        """Write JSON-RPC response to stdout.

        Serializes the response as JSON and writes it as a single
        line to stdout, followed by flush.
        """
        payload: dict[str, Any] = {
            "jsonrpc": response.jsonrpc,
            "id": response.id,
        }
        if response.result is not None:
            payload["result"] = response.result
        if response.error is not None:
            payload["error"] = response.error
        line = json.dumps(payload) + "\n"
        logger.info("→ Response: id=%s error=%s", response.id, response.error)
        logger.debug("SEND: %s", line.strip()[:500])
        sys.stdout.write(line)
        sys.stdout.flush()

    async def write_notification(self, notification: JsonRpcNotification) -> None:
        """Write JSON-RPC notification to stdout.

        Serializes the notification as JSON and writes it as a single
        line to stdout, followed by flush.
        """
        payload: dict[str, Any] = {
            "jsonrpc": notification.jsonrpc,
            "method": notification.method,
        }
        if notification.params is not None:
            payload["params"] = notification.params
        line = json.dumps(payload) + "\n"
        logger.info("→ Notification: %s", notification.method)
        logger.debug("SEND: %s", line.strip()[:500])
        sys.stdout.write(line)
        sys.stdout.flush()
