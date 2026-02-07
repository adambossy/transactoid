"""Tests for ACPServer."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from transactoid.ui.acp.server import ACPServer, main, run
from transactoid.ui.acp.transport import JsonRpcRequest


class TestACPServerInit:
    """Tests for ACPServer initialization."""

    def test_init_creates_db_with_provided_url(self) -> None:
        """ACPServer initializes DB with provided URL."""
        with (
            patch("transactoid.ui.acp.server.DB") as mock_db,
            patch(
                "transactoid.ui.acp.server.load_taxonomy_from_db"
            ) as mock_load_taxonomy,
            patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
        ):
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance
            mock_taxonomy = MagicMock()
            mock_load_taxonomy.return_value = mock_taxonomy
            mock_agent = MagicMock()
            mock_transactoid.return_value.create_agent.return_value = mock_agent

            server = ACPServer(db_url="postgresql://test:test@localhost/testdb")

            mock_db.assert_called_once_with("postgresql://test:test@localhost/testdb")
            assert server._db == mock_db_instance

    def test_init_uses_env_db_url_when_not_provided(self) -> None:
        """ACPServer uses DATABASE_URL env var when db_url not provided."""
        with (
            patch("transactoid.ui.acp.server.DB") as mock_db,
            patch(
                "transactoid.ui.acp.server.load_taxonomy_from_db"
            ) as mock_load_taxonomy,
            patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
            patch.dict(
                "os.environ", {"DATABASE_URL": "postgresql://env:env@localhost/envdb"}
            ),
        ):
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance
            mock_taxonomy = MagicMock()
            mock_load_taxonomy.return_value = mock_taxonomy
            mock_agent = MagicMock()
            mock_transactoid.return_value.create_agent.return_value = mock_agent

            server = ACPServer()

            mock_db.assert_called_once_with("postgresql://env:env@localhost/envdb")
            assert server._db == mock_db_instance

    def test_init_loads_taxonomy(self) -> None:
        """ACPServer loads taxonomy from database."""
        with (
            patch("transactoid.ui.acp.server.DB") as mock_db,
            patch(
                "transactoid.ui.acp.server.load_taxonomy_from_db"
            ) as mock_load_taxonomy,
            patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
        ):
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance
            mock_taxonomy = MagicMock()
            mock_load_taxonomy.return_value = mock_taxonomy
            mock_agent = MagicMock()
            mock_transactoid.return_value.create_agent.return_value = mock_agent

            server = ACPServer(db_url="sqlite:///:memory:")

            mock_load_taxonomy.assert_called_once_with(mock_db_instance)
            assert server._taxonomy == mock_taxonomy

    def test_init_creates_agent(self) -> None:
        """ACPServer creates agent from Transactoid orchestrator."""
        with (
            patch("transactoid.ui.acp.server.DB") as mock_db,
            patch(
                "transactoid.ui.acp.server.load_taxonomy_from_db"
            ) as mock_load_taxonomy,
            patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
        ):
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance
            mock_taxonomy = MagicMock()
            mock_load_taxonomy.return_value = mock_taxonomy
            mock_transactoid_instance = MagicMock()
            mock_agent = MagicMock()
            mock_transactoid_instance.create_agent.return_value = mock_agent
            mock_transactoid.return_value = mock_transactoid_instance

            server = ACPServer(db_url="sqlite:///:memory:")

            mock_transactoid.assert_called_once_with(
                db=mock_db_instance, taxonomy=mock_taxonomy
            )
            mock_transactoid_instance.create_agent.assert_called_once()
            assert server._agent == mock_agent

    def test_init_registers_handlers(self) -> None:
        """ACPServer registers all protocol handlers."""
        with (
            patch("transactoid.ui.acp.server.DB") as mock_db,
            patch(
                "transactoid.ui.acp.server.load_taxonomy_from_db"
            ) as mock_load_taxonomy,
            patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
        ):
            mock_db.return_value = MagicMock()
            mock_load_taxonomy.return_value = MagicMock()
            mock_transactoid.return_value.create_agent.return_value = MagicMock()

            server = ACPServer(db_url="sqlite:///:memory:")

            # Verify handlers are registered
            assert server._router.has_method("initialize")
            assert server._router.has_method("session/new")
            assert server._router.has_method("session/prompt")


def _create_mock_server() -> ACPServer:
    """Create a server with mocked dependencies."""
    with (
        patch("transactoid.ui.acp.server.DB"),
        patch("transactoid.ui.acp.server.load_taxonomy_from_db"),
        patch("transactoid.ui.acp.server.Transactoid") as mock_transactoid,
    ):
        mock_transactoid.return_value.create_agent.return_value = MagicMock()
        return ACPServer(db_url="sqlite:///:memory:")


def _run_server_with_requests(
    server: ACPServer, requests: list[JsonRpcRequest]
) -> list[Any]:
    """Run server with mock requests and collect responses."""
    responses: list[Any] = []

    async def capture_response(response: Any) -> None:
        responses.append(response)

    with (
        patch.object(
            server._transport,
            "read_message",
            AsyncMock(side_effect=[*requests, EOFError()]),
        ),
        patch.object(
            server._transport,
            "write_response",
            AsyncMock(side_effect=capture_response),
        ),
    ):
        asyncio.run(server.run())

    return responses


class TestACPServerRun:
    """Tests for ACPServer run loop."""

    def test_run_exits_on_eof(self) -> None:
        """ACPServer run loop exits gracefully on EOFError."""
        server = _create_mock_server()
        with patch.object(
            server._transport, "read_message", AsyncMock(side_effect=EOFError)
        ):
            # Should complete without error
            asyncio.run(server.run())

    def test_run_dispatches_initialize(self) -> None:
        """ACPServer dispatches initialize requests."""
        server = _create_mock_server()
        request = JsonRpcRequest(
            method="initialize",
            id=1,
            params={"protocolVersion": 1},
        )

        responses = _run_server_with_requests(server, [request])

        assert len(responses) == 1
        response = responses[0]
        assert response.id == 1
        assert response.result is not None
        assert "protocolVersion" in response.result

    def test_run_dispatches_session_new(self) -> None:
        """ACPServer dispatches session/new requests."""
        server = _create_mock_server()
        request = JsonRpcRequest(
            method="session/new",
            id=2,
            params={"cwd": "/home/user"},
        )

        responses = _run_server_with_requests(server, [request])

        assert len(responses) == 1
        response = responses[0]
        assert response.id == 2
        assert response.result is not None
        assert "sessionId" in response.result

    def test_run_handles_method_not_found(self) -> None:
        """ACPServer returns error for unknown methods."""
        server = _create_mock_server()
        request = JsonRpcRequest(
            method="unknown/method",
            id=3,
            params={},
        )

        responses = _run_server_with_requests(server, [request])

        assert len(responses) == 1
        response = responses[0]
        assert response.id == 3
        assert response.error is not None
        assert response.error["code"] == -32601
        assert "unknown/method" in response.error["message"]

    def test_run_handles_handler_exception(self) -> None:
        """ACPServer returns internal error for handler exceptions."""
        server = _create_mock_server()
        request = JsonRpcRequest(
            method="initialize",
            id=4,
            params={},
        )

        # Make the router raise an exception
        async def failing_handler(params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Handler failed")

        server._router.register("initialize", failing_handler)

        responses = _run_server_with_requests(server, [request])

        assert len(responses) == 1
        response = responses[0]
        assert response.id == 4
        assert response.error is not None
        assert response.error["code"] == -32603
        assert "Handler failed" in response.error["message"]

    def test_run_handles_multiple_requests(self) -> None:
        """ACPServer processes multiple requests before EOF."""
        server = _create_mock_server()
        requests = [
            JsonRpcRequest(method="initialize", id=1, params={}),
            JsonRpcRequest(method="session/new", id=2, params={"cwd": "/home/user"}),
        ]

        responses = _run_server_with_requests(server, requests)

        assert len(responses) == 2


class TestMain:
    """Tests for main entry point."""

    def test_main_creates_and_runs_server(self) -> None:
        """main() creates ACPServer and runs it."""
        with (
            patch("transactoid.ui.acp.server.ACPServer") as mock_server_class,
        ):
            mock_server = MagicMock()
            mock_server.run = AsyncMock()
            mock_server_class.return_value = mock_server

            asyncio.run(main())

            mock_server_class.assert_called_once()
            mock_server.run.assert_called_once()


class TestRun:
    """Tests for synchronous run entry point."""

    def test_run_calls_asyncio_run(self) -> None:
        """run() calls asyncio.run with main()."""
        with (
            patch("transactoid.ui.acp.server.asyncio.run") as mock_asyncio_run,
            patch("transactoid.ui.acp.server.main"),
        ):
            run()

            mock_asyncio_run.assert_called_once()
            # The argument should be the coroutine from main()
            call_arg = mock_asyncio_run.call_args[0][0]
            assert asyncio.iscoroutine(call_arg)
