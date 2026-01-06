"""Initialize handler for ACP protocol.

Handles the 'initialize' JSON-RPC method, which is the first message
exchanged between client and agent to establish the connection and
negotiate capabilities.
"""

from __future__ import annotations

from typing import Any

# Current protocol version supported by this server
PROTOCOL_VERSION = 1


async def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    """Handle the ACP 'initialize' request.

    Performs capability negotiation between client and agent, returning
    the agent's capabilities and version information.

    Args:
        params: Request parameters containing:
            - protocolVersion: Client's protocol version
            - clientCapabilities: Dict of client capabilities
            - clientInfo: Client name and version info

    Returns:
        Response dict containing:
            - protocolVersion: Negotiated protocol version (min of client/agent)
            - agentCapabilities: Dict of agent capabilities
            - agentInfo: Agent name, title, and version
            - authMethods: List of supported auth methods (empty for now)
    """
    client_version = params.get("protocolVersion", 1)

    # Negotiate protocol version (use minimum of client/agent versions)
    negotiated_version = min(client_version, PROTOCOL_VERSION)

    return {
        "protocolVersion": negotiated_version,
        "agentCapabilities": {
            "promptTypes": {
                "image": False,
                "audio": False,
                "embeddedContext": True,
            },
            "mcp": {
                "http": False,
                "sse": False,
            },
        },
        "agentInfo": {
            "name": "transactoid",
            "title": "Transactoid Finance Agent",
            "version": "0.1.0",
        },
        "authMethods": [],
    }
