"""Tests for ACP initialize handler."""

from __future__ import annotations

import asyncio
from typing import Any

from transactoid.ui.acp.handlers.initialize import (
    PROTOCOL_VERSION,
    handle_initialize,
)


def _run_async(coro: Any) -> Any:
    """Run an async function synchronously."""
    return asyncio.run(coro)


class TestHandleInitialize:
    """Tests for handle_initialize function."""

    def test_initialize_returns_protocol_version(self) -> None:
        """Test that initialize returns the protocol version."""
        params: dict[str, Any] = {"protocolVersion": 1}

        result = _run_async(handle_initialize(params))

        assert result["protocolVersion"] == 1

    def test_initialize_negotiates_lower_version(self) -> None:
        """Test version negotiation uses minimum of client/agent."""
        params: dict[str, Any] = {"protocolVersion": 99}

        result = _run_async(handle_initialize(params))

        assert result["protocolVersion"] == PROTOCOL_VERSION

    def test_initialize_uses_client_version_if_lower(self) -> None:
        """Test version negotiation uses client version if lower."""
        params: dict[str, Any] = {"protocolVersion": 0}

        result = _run_async(handle_initialize(params))

        assert result["protocolVersion"] == 0

    def test_initialize_returns_agent_capabilities(self) -> None:
        """Test that initialize returns agent capabilities."""
        params: dict[str, Any] = {"protocolVersion": 1}

        result = _run_async(handle_initialize(params))

        assert "agentCapabilities" in result
        capabilities = result["agentCapabilities"]
        assert capabilities["promptTypes"]["image"] is False
        assert capabilities["promptTypes"]["audio"] is False
        assert capabilities["promptTypes"]["embeddedContext"] is True
        assert capabilities["mcp"]["http"] is False
        assert capabilities["mcp"]["sse"] is False

    def test_initialize_returns_agent_info(self) -> None:
        """Test that initialize returns agent info."""
        params: dict[str, Any] = {"protocolVersion": 1}

        result = _run_async(handle_initialize(params))

        assert "agentInfo" in result
        info = result["agentInfo"]
        assert info["name"] == "transactoid"
        assert info["title"] == "Transactoid Finance Agent"
        assert info["version"] == "0.1.0"

    def test_initialize_returns_empty_auth_methods(self) -> None:
        """Test that initialize returns empty auth methods."""
        params: dict[str, Any] = {"protocolVersion": 1}

        result = _run_async(handle_initialize(params))

        assert result["authMethods"] == []

    def test_initialize_with_client_capabilities(self) -> None:
        """Test that initialize handles client capabilities (currently ignored)."""
        params: dict[str, Any] = {
            "protocolVersion": 1,
            "clientCapabilities": {
                "readTextFile": True,
                "writeTextFile": True,
                "terminal": True,
            },
            "clientInfo": {"name": "cursor", "version": "1.0.0"},
        }

        result = _run_async(handle_initialize(params))

        # Client capabilities are accepted but not used yet
        assert result["protocolVersion"] == 1
        assert result["agentInfo"]["name"] == "transactoid"

    def test_initialize_with_missing_protocol_version(self) -> None:
        """Test that initialize defaults to version 1 if not provided."""
        params: dict[str, Any] = {}

        result = _run_async(handle_initialize(params))

        assert result["protocolVersion"] == 1
