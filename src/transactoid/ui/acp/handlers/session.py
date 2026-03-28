"""Session management handlers for ACP protocol.

Provides session creation, retrieval, and message management for ACP
conversations. Each session maintains its own conversation history
and working directory context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

from loguru import logger

from transactoid.adapters.storage.r2 import R2DownloadError
from transactoid.services.agent_run.state import (
    ContinuationState,
    ContinuationStateError,
    download_continuation_state,
)


@dataclass
class Session:
    """ACP session state.

    Represents a single conversation session with the agent, maintaining
    context like working directory and message history.

    Attributes:
        id: Unique session identifier (format: sess_<12-char-hex>)
        cwd: Client's current working directory
        mcp_servers: List of MCP server configurations from client
        messages: Conversation history as list of message dicts
        continuation_state: Prior run state for resumed sessions,
            consumed on first prompt.
    """

    id: str
    cwd: str
    mcp_servers: list[dict[str, Any]]
    messages: list[dict[str, Any]] = field(default_factory=list)
    continuation_state: ContinuationState | None = None


class SessionManager:
    """Manage ACP sessions.

    Provides lifecycle management for sessions including creation,
    retrieval, and message tracking. Sessions are stored in memory
    and do not persist across server restarts.

    Example:
        manager = SessionManager()
        session_id = manager.create(cwd="/home/user", mcp_servers=[])
        session = manager.get(session_id)
        manager.add_message(session_id, {"role": "user", "content": "Hello"})
    """

    def __init__(self) -> None:
        """Initialize the session manager with an empty session store."""
        self._sessions: dict[str, Session] = {}

    def create(self, cwd: str, mcp_servers: list[dict[str, Any]]) -> str:
        """Create a new session.

        Args:
            cwd: Client's current working directory
            mcp_servers: List of MCP server configurations

        Returns:
            New session ID (format: sess_<12-char-hex>)
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = Session(
            id=session_id,
            cwd=cwd,
            mcp_servers=mcp_servers,
        )
        return session_id

    def create_with_continuation(
        self,
        *,
        cwd: str,
        mcp_servers: list[dict[str, Any]],
        continuation_state: ContinuationState,
    ) -> str:
        """Create a new session pre-loaded with prior run context.

        Args:
            cwd: Client's current working directory.
            mcp_servers: List of MCP server configurations.
            continuation_state: Prior run state to inject on first prompt.

        Returns:
            New session ID (format: sess_<12-char-hex>).
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = Session(
            id=session_id,
            cwd=cwd,
            mcp_servers=mcp_servers,
            continuation_state=continuation_state,
        )
        return session_id

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID.

        Args:
            session_id: The session identifier to look up

        Returns:
            Session instance if found, None otherwise
        """
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, message: dict[str, Any]) -> bool:
        """Add a message to session history.

        Args:
            session_id: The session to add the message to
            message: Message dict to append to history

        Returns:
            True if message was added, False if session not found
        """
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.messages.append(message)
        return True

    def __len__(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        """Check if a session exists."""
        return session_id in self._sessions


async def handle_session_new(
    params: dict[str, Any],
    session_manager: SessionManager,
) -> dict[str, Any]:
    """Handle the ACP 'session/new' request.

    Creates a new session with the provided context and returns
    the session identifier.

    Args:
        params: Request parameters containing:
            - cwd: Client's current working directory
            - mcpServers: Optional list of MCP server configurations
        session_manager: SessionManager instance to create the session

    Returns:
        Response dict containing:
            - sessionId: Unique identifier for the new session
    """
    cwd = params.get("cwd", "")
    mcp_servers: list[dict[str, Any]] = params.get("mcpServers", [])

    session_id = session_manager.create(cwd=cwd, mcp_servers=mcp_servers)

    return {"sessionId": session_id}


async def handle_session_resume(
    params: dict[str, Any],
    session_manager: SessionManager,
) -> dict[str, Any]:
    """Handle the ACP 'session/resume' request.

    Downloads continuation state for a prior headless run from R2 and
    creates a new session pre-loaded with that context. The first
    ``session/prompt`` call on this session will prepend prior turns
    as context blocks.

    Args:
        params: Request parameters containing:
            - runId: Required. The headless run ID to resume.
            - cwd: Client's current working directory.
            - mcpServers: Optional list of MCP server configurations.
        session_manager: SessionManager instance to create the session.

    Returns:
        Response dict containing:
            - sessionId: Unique identifier for the resumed session.
        Or error dict on failure.
    """
    run_id = params.get("runId")
    if not run_id or not isinstance(run_id, str):
        return {
            "error": {
                "code": -32602,
                "message": "Missing required parameter: runId",
            }
        }

    cwd = params.get("cwd", "")
    mcp_servers: list[dict[str, Any]] = params.get("mcpServers", [])

    try:
        state = download_continuation_state(run_id=run_id)
    except R2DownloadError:
        logger.warning("session/resume: run not found: {}", run_id)
        return {
            "error": {
                "code": -32602,
                "message": f"Run not found: {run_id}",
            }
        }
    except ContinuationStateError:
        logger.warning("session/resume: corrupt state for run: {}", run_id)
        return {
            "error": {
                "code": -32602,
                "message": f"Corrupt state for run: {run_id}",
            }
        }

    session_id = session_manager.create_with_continuation(
        cwd=cwd,
        mcp_servers=mcp_servers,
        continuation_state=state,
    )
    logger.info("session/resume: created session {} from run {}", session_id, run_id)

    return {"sessionId": session_id}
