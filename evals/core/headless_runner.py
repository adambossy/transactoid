from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from agents import Agent, Runner, SQLiteSession
from agents.items import MessageOutputItem

from orchestrators.transactoid import Transactoid
from services.db import DB
from services.taxonomy import Taxonomy


class MockPlaidClient:
    """Mock Plaid client for evals that avoids real API calls.
    
    Returns test data for any Plaid item in the database, allowing
    the agent to proceed without hitting the real Plaid API.
    """

    def __init__(self, db: DB) -> None:
        """Initialize mock with database reference.

        Args:
            db: Database instance for looking up PlaidItem records
        """
        self._db = db

    def list_accounts(self, db: DB) -> dict[str, Any]:
        """List accounts for all Plaid items in the database.

        Args:
            db: Database instance

        Returns:
            Dictionary with status and accounts list
        """
        try:
            plaid_items = db.list_plaid_items()
            if not plaid_items:
                return {
                    "status": "success",
                    "accounts": [],
                    "message": "No connected accounts found.",
                }

            # For each PlaidItem, return a dummy account
            accounts = []
            for item in plaid_items:
                accounts.append(
                    {
                        "account_id": f"account_{item.item_id}",
                        "name": item.institution_name or f"Account for {item.item_id}",
                        "official_name": item.institution_name,
                        "mask": "****",
                        "subtype": "checking",
                        "type": "depository",
                        "institution": item.institution_name,
                    }
                )

            return {
                "status": "success",
                "accounts": accounts,
                "message": f"Found {len(accounts)} account(s).",
            }
        except Exception as e:
            return {
                "status": "error",
                "accounts": [],
                "message": f"Failed to list accounts: {e}",
            }

    def get_accounts(self, access_token: str) -> list[dict[str, Any]]:
        """Get accounts for an access token (mocked).

        Args:
            access_token: Access token (ignored in mock)

        Returns:
            Empty list (accounts are returned via list_accounts)
        """
        return []

    def connect_new_account(self, db: DB) -> dict[str, Any]:
        """Attempt to connect a new account (always fails in eval).

        Args:
            db: Database instance

        Returns:
            Error dictionary
        """
        return {
            "status": "error",
            "message": "Cannot connect accounts in eval mode",
        }

    def sync_transactions(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Sync transactions (mocked for eval).

        Accepts any positional or keyword arguments and ignores them.

        Returns:
            Success with zero transactions (fixture data is already in DB)
        """
        return {
            "status": "success",
            "pages_processed": 0,
            "total_added": 0,
            "total_modified": 0,
            "total_removed": 0,
        }


@dataclass
class AgentTurn:
    """Result of a single conversation turn."""

    question: str
    response: str
    tool_calls: list[dict[str, Any]]
    reasoning: str
    duration_seconds: float


@dataclass
class ConversationResult:
    """Result of complete conversation (single or multi-turn)."""

    turns: list[AgentTurn]
    total_duration_seconds: float

    @property
    def full_conversation(self) -> str:
        """Format as Q&A pairs for judge."""
        parts = []
        for turn in self.turns:
            parts.append(f"Q: {turn.question}\nA: {turn.response}")
        return "\n\n".join(parts)


class HeadlessAgentRunner:
    """Runs Transactoid agent without terminal output."""

    def __init__(self, db: DB, taxonomy: Taxonomy) -> None:
        """Initialize headless runner.

        Args:
            db: Database instance
            taxonomy: Taxonomy instance
        """
        self._db = db
        self._taxonomy = taxonomy

    async def run_conversation(
        self,
        initial_question: str,
        follow_ups: list[str],
    ) -> ConversationResult:
        """Run multi-turn conversation with agent.

        Args:
            initial_question: First question to ask
            follow_ups: List of follow-up questions

        Returns:
            ConversationResult with all turns
        """
        # Create agent with inline tools
        agent = self._create_agent()
        session = SQLiteSession(session_id="eval")

        turns: list[AgentTurn] = []
        total_start = time.time()

        # Run initial question
        turn = await self._run_single_turn(agent, session, initial_question)
        turns.append(turn)

        # Run follow-ups
        for follow_up in follow_ups:
            turn = await self._run_single_turn(agent, session, follow_up)
            turns.append(turn)

        return ConversationResult(
            turns=turns,
            total_duration_seconds=time.time() - total_start,
        )

    async def _run_single_turn(
        self, agent: Agent, session: SQLiteSession, question: str
    ) -> AgentTurn:
        """Run one turn with Runner.run() (non-streaming).

        Args:
            agent: Agent instance
            session: Session for conversation context
            question: User question

        Returns:
            AgentTurn with captured data
        """
        start = time.time()

        # Use Runner.run() for complete result
        result = await Runner.run(agent, input=question, session=session)

        # Extract data from result
        response = self._extract_response(result)
        tool_calls = self._extract_tool_calls(result)
        reasoning = self._extract_reasoning(result)

        return AgentTurn(
            question=question,
            response=response,
            tool_calls=tool_calls,
            reasoning=reasoning,
            duration_seconds=time.time() - start,
        )

    def _extract_response(self, result: Any) -> str:
        """Extract final response text from result."""
        # Try to get from final_output first (standard way)
        if hasattr(result, "final_output") and result.final_output:
            if isinstance(result.final_output, str):
                return result.final_output
            # If final_output is a dict or object, try to get text
            if hasattr(result.final_output, "text"):
                return str(result.final_output.text)

        # Fallback: Find MessageOutputItem in result.new_items
        for item in result.new_items:
            if isinstance(item, MessageOutputItem):
                # Get text from content
                if hasattr(item, "content") and item.content:
                    for content_item in item.content:
                        if hasattr(content_item, "text"):
                            text: str = str(content_item.text)
                            return text
        return ""

    def _extract_tool_calls(self, result: Any) -> list[dict[str, Any]]:
        """Extract tool calls from result.new_items."""
        calls = []
        for item in result.new_items:
            if hasattr(item, "type") and item.type == "tool_call_output_item":
                # Extract data from raw_item
                raw = item.raw_item
                name = ""
                arguments = {}
                if isinstance(raw, dict):
                    name = raw.get("function", {}).get("name", "")
                    arguments_str = raw.get("function", {}).get("arguments", "{}")
                    try:
                        import json
                        arguments = json.loads(arguments_str) if arguments_str else {}
                    except Exception:
                        arguments = {}
                else:
                    # Try to get name from raw object attributes
                    if hasattr(raw, "function"):
                        if hasattr(raw.function, "name"):
                            name = raw.function.name
                        if hasattr(raw.function, "arguments"):
                            try:
                                import json
                                arguments = json.loads(raw.function.arguments)
                            except Exception:
                                arguments = {}

                calls.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "result": item.output if hasattr(item, "output") else None,
                    }
                )
        return calls

    def _extract_reasoning(self, result: Any) -> str:
        """Extract reasoning from result."""
        # Check if result has reasoning attribute
        if hasattr(result, "reasoning") and result.reasoning:
            if hasattr(result.reasoning, "content"):
                content: str = str(result.reasoning.content)
                return content
        return ""

    def _create_agent(self) -> Agent:
        """Create agent using the production Transactoid orchestrator."""
        # Create mock Plaid client for evals to avoid real API calls
        mock_plaid = MockPlaidClient(self._db)
        
        # Create Transactoid instance with mock Plaid client
        transactoid = Transactoid(
            db=self._db,
            taxonomy=self._taxonomy,
            plaid_client=mock_plaid,
        )
        return transactoid.create_agent()
