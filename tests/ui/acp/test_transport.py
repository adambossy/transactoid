"""Tests for ACP JSON-RPC transport layer."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from unittest.mock import patch

import pytest

from transactoid.ui.acp.transport import (
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    StdioTransport,
)


class TestJsonRpcRequest:
    """Tests for JsonRpcRequest dataclass."""

    def test_request_with_all_fields(self) -> None:
        request = JsonRpcRequest(
            method="initialize",
            id=1,
            params={"protocolVersion": 1},
            jsonrpc="2.0",
        )

        assert request.method == "initialize"
        assert request.id == 1
        assert request.params == {"protocolVersion": 1}
        assert request.jsonrpc == "2.0"

    def test_request_with_defaults(self) -> None:
        request = JsonRpcRequest(method="ping")

        assert request.method == "ping"
        assert request.id is None
        assert request.params is None
        assert request.jsonrpc == "2.0"

    def test_request_with_string_id(self) -> None:
        request = JsonRpcRequest(method="test", id="abc-123")

        assert request.id == "abc-123"

    def test_request_is_frozen(self) -> None:
        request = JsonRpcRequest(method="test")

        with pytest.raises(AttributeError):
            request.method = "changed"  # type: ignore[misc]


class TestJsonRpcResponse:
    """Tests for JsonRpcResponse dataclass."""

    def test_response_with_result(self) -> None:
        response = JsonRpcResponse(
            id=1,
            result={"protocolVersion": 1},
        )

        assert response.id == 1
        assert response.result == {"protocolVersion": 1}
        assert response.error is None
        assert response.jsonrpc == "2.0"

    def test_response_with_error(self) -> None:
        response = JsonRpcResponse(
            id=1,
            error={"code": -32600, "message": "Invalid Request"},
        )

        assert response.id == 1
        assert response.result is None
        assert response.error == {"code": -32600, "message": "Invalid Request"}

    def test_response_with_null_id(self) -> None:
        response = JsonRpcResponse(
            id=None,
            error={"code": -32700, "message": "Parse error"},
        )

        assert response.id is None

    def test_response_is_frozen(self) -> None:
        response = JsonRpcResponse(id=1, result={})

        with pytest.raises(AttributeError):
            response.id = 2  # type: ignore[misc]


class TestJsonRpcNotification:
    """Tests for JsonRpcNotification dataclass."""

    def test_notification_with_params(self) -> None:
        notification = JsonRpcNotification(
            method="session/update",
            params={"update": {"sessionUpdate": "message_delta"}},
        )

        assert notification.method == "session/update"
        assert notification.params == {"update": {"sessionUpdate": "message_delta"}}
        assert notification.jsonrpc == "2.0"

    def test_notification_without_params(self) -> None:
        notification = JsonRpcNotification(method="shutdown")

        assert notification.method == "shutdown"
        assert notification.params is None

    def test_notification_is_frozen(self) -> None:
        notification = JsonRpcNotification(method="test")

        with pytest.raises(AttributeError):
            notification.method = "changed"  # type: ignore[misc]


class TestStdioTransport:
    """Tests for StdioTransport class."""

    def test_read_message_parses_valid_json_rpc(self) -> None:
        input_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": 1},
        }
        mock_stdin = io.StringIO(json.dumps(input_data) + "\n")

        async def run_test() -> JsonRpcRequest:
            transport = StdioTransport()
            with patch("sys.stdin", mock_stdin):
                return await transport.read_message()

        result = asyncio.run(run_test())

        expected = JsonRpcRequest(
            method="initialize",
            id=1,
            params={"protocolVersion": 1},
            jsonrpc="2.0",
        )
        assert result == expected

    def test_read_message_raises_eof_on_empty_input(self) -> None:
        mock_stdin = io.StringIO("")

        async def run_test() -> JsonRpcRequest:
            transport = StdioTransport()
            with patch("sys.stdin", mock_stdin):
                return await transport.read_message()

        with pytest.raises(EOFError, match="stdin closed"):
            asyncio.run(run_test())

    def test_read_message_raises_on_invalid_json(self) -> None:
        mock_stdin = io.StringIO("not valid json\n")

        async def run_test() -> JsonRpcRequest:
            transport = StdioTransport()
            with patch("sys.stdin", mock_stdin):
                return await transport.read_message()

        with pytest.raises(json.JSONDecodeError):
            asyncio.run(run_test())

    def test_read_message_handles_missing_optional_fields(self) -> None:
        input_data = {"jsonrpc": "2.0", "method": "ping"}
        mock_stdin = io.StringIO(json.dumps(input_data) + "\n")

        async def run_test() -> JsonRpcRequest:
            transport = StdioTransport()
            with patch("sys.stdin", mock_stdin):
                return await transport.read_message()

        result = asyncio.run(run_test())

        assert result.method == "ping"
        assert result.id is None
        assert result.params is None

    def test_write_response_formats_result(self) -> None:
        mock_stdout = io.StringIO()
        response = JsonRpcResponse(
            id=1,
            result={"protocolVersion": 1},
        )

        async def run_test() -> None:
            transport = StdioTransport()
            with patch("sys.stdout", mock_stdout):
                await transport.write_response(response)

        asyncio.run(run_test())

        output = mock_stdout.getvalue()
        parsed: dict[str, Any] = json.loads(output.strip())

        expected = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": 1},
        }
        assert parsed == expected

    def test_write_response_formats_error(self) -> None:
        mock_stdout = io.StringIO()
        response = JsonRpcResponse(
            id=1,
            error={"code": -32600, "message": "Invalid Request"},
        )

        async def run_test() -> None:
            transport = StdioTransport()
            with patch("sys.stdout", mock_stdout):
                await transport.write_response(response)

        asyncio.run(run_test())

        output = mock_stdout.getvalue()
        parsed: dict[str, Any] = json.loads(output.strip())

        assert parsed["error"] == {"code": -32600, "message": "Invalid Request"}
        assert "result" not in parsed

    def test_write_notification_formats_correctly(self) -> None:
        mock_stdout = io.StringIO()
        notification = JsonRpcNotification(
            method="session/update",
            params={"update": {"sessionUpdate": "message_delta"}},
        )

        async def run_test() -> None:
            transport = StdioTransport()
            with patch("sys.stdout", mock_stdout):
                await transport.write_notification(notification)

        asyncio.run(run_test())

        output = mock_stdout.getvalue()
        parsed: dict[str, Any] = json.loads(output.strip())

        expected = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "message_delta"}},
        }
        assert parsed == expected

    def test_write_notification_omits_null_params(self) -> None:
        mock_stdout = io.StringIO()
        notification = JsonRpcNotification(method="shutdown")

        async def run_test() -> None:
            transport = StdioTransport()
            with patch("sys.stdout", mock_stdout):
                await transport.write_notification(notification)

        asyncio.run(run_test())

        output = mock_stdout.getvalue()
        parsed: dict[str, Any] = json.loads(output.strip())

        assert "params" not in parsed

    def test_multiple_read_write_operations(self) -> None:
        input_data = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {}},
        ]
        mock_stdin = io.StringIO("\n".join(json.dumps(d) for d in input_data) + "\n")
        mock_stdout = io.StringIO()

        async def run_test() -> tuple[JsonRpcRequest, JsonRpcRequest]:
            transport = StdioTransport()
            with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
                req1 = await transport.read_message()
                await transport.write_response(JsonRpcResponse(id=req1.id, result={}))

                req2 = await transport.read_message()
                await transport.write_response(JsonRpcResponse(id=req2.id, result={}))
                return req1, req2

        req1, req2 = asyncio.run(run_test())

        assert req1.method == "initialize"
        assert req2.method == "session/new"

        lines = mock_stdout.getvalue().strip().split("\n")
        assert len(lines) == 2
