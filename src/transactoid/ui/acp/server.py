"""ACP (Agent Client Protocol) server implementation.

Main server class that initializes services, registers protocol handlers,
and runs the event loop for processing JSON-RPC requests over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv

# Configure logging to stderr (stdout is reserved for JSON-RPC)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# These imports must be after logging.basicConfig to capture import-time logs
from transactoid.adapters.db.facade import DB  # noqa: E402
from transactoid.orchestrators.transactoid import Transactoid  # noqa: E402
from transactoid.taxonomy.loader import load_taxonomy_from_db  # noqa: E402
from transactoid.ui.acp.handlers import (  # noqa: E402
    PromptHandler,
    SessionManager,
    handle_initialize,
    handle_session_new,
)
from transactoid.ui.acp.notifier import UpdateNotifier  # noqa: E402
from transactoid.ui.acp.router import MethodNotFoundError, RequestRouter  # noqa: E402
from transactoid.ui.acp.transport import JsonRpcResponse, StdioTransport  # noqa: E402


class ACPServer:
    """ACP server for the Transactoid finance agent.

    Initializes services (DB, Taxonomy), creates the agent, registers
    protocol handlers, and runs the main event loop processing JSON-RPC
    requests from stdin and writing responses to stdout.

    Example:
        server = ACPServer()
        await server.run()

    The server handles these JSON-RPC methods:
    - initialize: Capability negotiation with client
    - session/new: Create a new conversation session
    - session/prompt: Process user prompts and stream responses
    """

    def __init__(self, db_url: str | None = None) -> None:
        """Initialize the ACP server.

        Args:
            db_url: Database URL. If None, uses DATABASE_URL env var
                or falls back to sqlite:///:memory:.
        """
        # Load environment variables
        load_dotenv()

        # Initialize database
        if db_url is None:
            db_url = os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        self._db = DB(db_url)

        # Load taxonomy from database
        self._taxonomy = load_taxonomy_from_db(self._db)

        # Create Transactoid orchestrator and agent
        self._transactoid = Transactoid(db=self._db, taxonomy=self._taxonomy)
        self._agent = self._transactoid.create_agent()

        # Initialize transport layer
        self._transport = StdioTransport()

        # Initialize notifier for session updates
        self._notifier = UpdateNotifier(self._transport)

        # Initialize session manager
        self._sessions = SessionManager()

        # Initialize prompt handler
        self._prompt_handler = PromptHandler(
            session_manager=self._sessions,
            agent=self._agent,
            notifier=self._notifier,
        )

        # Initialize and configure router
        self._router = RequestRouter()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register all protocol handlers with the router."""
        # Register initialize handler
        self._router.register("initialize", handle_initialize)

        # Register session/new handler with session manager
        async def session_new_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await handle_session_new(params, self._sessions)

        self._router.register("session/new", session_new_handler)

        # Register session/prompt handler
        async def session_prompt_handler(params: dict[str, Any]) -> dict[str, Any]:
            return await self._prompt_handler.handle_prompt(params)

        self._router.register("session/prompt", session_prompt_handler)

    async def run(self) -> None:
        """Run the main event loop.

        Reads JSON-RPC requests from stdin, dispatches them to the
        appropriate handler, and writes responses to stdout.

        The loop continues until stdin is closed (EOFError) or a
        shutdown is requested.
        """
        logger.info("ACP server starting event loop")
        while True:
            try:
                # Read next request from stdin
                request = await self._transport.read_message()

                # Dispatch to handler
                try:
                    params = request.params or {}
                    logger.info("Dispatching %s (id=%s)", request.method, request.id)
                    result = await self._router.dispatch(request.method, params)
                    logger.info(
                        "Handler completed for %s (id=%s)", request.method, request.id
                    )

                    # Send success response
                    response = JsonRpcResponse(
                        id=request.id,
                        result=result,
                    )
                except MethodNotFoundError as e:
                    logger.warning("Method not found: %s", e.method)
                    # Send method not found error
                    response = JsonRpcResponse(
                        id=request.id,
                        error={
                            "code": -32601,
                            "message": f"Method not found: {e.method}",
                        },
                    )
                except Exception as e:
                    logger.exception("Handler error for %s: %s", request.method, e)
                    # Send internal error
                    response = JsonRpcResponse(
                        id=request.id,
                        error={
                            "code": -32603,
                            "message": f"Internal error: {e}",
                        },
                    )

                # Write response
                await self._transport.write_response(response)

            except EOFError:
                logger.info("stdin closed, shutting down")
                # stdin closed, exit gracefully
                break


async def main() -> None:
    """Entry point for the transactoid-acp command."""
    logger.info("=== Transactoid ACP Server Starting ===")
    server = ACPServer()
    logger.info("Server initialized, starting run loop...")
    await server.run()
    logger.info("=== Transactoid ACP Server Stopped ===")


def run() -> None:
    """Synchronous entry point for script invocation."""
    asyncio.run(main())
