from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from transactoid.adapters.db.facade import DB
from transactoid.core.runtime.protocol import CoreRunResult, CoreRuntime, ToolCallRecord
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.taxonomy.core import Taxonomy


class MockPlaidClient:
    """Mock Plaid client for evals that avoids real API calls."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def list_accounts(self, db: DB) -> dict[str, Any]:
        try:
            plaid_items = db.list_plaid_items()
            if not plaid_items:
                return {
                    "status": "success",
                    "accounts": [],
                    "message": "No connected accounts found.",
                }

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
        _ = access_token
        return []

    def connect_new_account(self, db: DB) -> dict[str, Any]:
        _ = db
        return {
            "status": "error",
            "message": "Cannot connect accounts in eval mode",
        }

    def sync_transactions(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = (args, kwargs)
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
        parts = []
        for turn in self.turns:
            parts.append(f"Q: {turn.question}\nA: {turn.response}")
        return "\n\n".join(parts)


class HeadlessAgentRunner:
    """Runs Transactoid agent without terminal output."""

    def __init__(self, db: DB, taxonomy: Taxonomy) -> None:
        self._db = db
        self._taxonomy = taxonomy

    async def run_conversation(
        self,
        initial_question: str,
        follow_ups: list[str],
    ) -> ConversationResult:
        runtime = self._create_runtime()
        session = runtime.start_session("eval")

        turns: list[AgentTurn] = []
        total_start = time.time()

        turn = await self._run_single_turn(runtime, session, initial_question)
        turns.append(turn)

        for follow_up in follow_ups:
            turn = await self._run_single_turn(runtime, session, follow_up)
            turns.append(turn)

        return ConversationResult(
            turns=turns,
            total_duration_seconds=time.time() - total_start,
        )

    async def _run_single_turn(
        self,
        runtime: CoreRuntime,
        session: Any,
        question: str,
    ) -> AgentTurn:
        start = time.time()
        result: CoreRunResult = await runtime.run(input_text=question, session=session)

        response = result.final_text
        tool_calls = self._extract_tool_calls(result.tool_calls)
        reasoning = ""

        return AgentTurn(
            question=question,
            response=response,
            tool_calls=tool_calls,
            reasoning=reasoning,
            duration_seconds=time.time() - start,
        )

    def _extract_tool_calls(
        self, tool_calls: list[ToolCallRecord]
    ) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for call in tool_calls:
            calls.append(
                {
                    "name": call.tool_name,
                    "arguments": call.arguments,
                    "result": call.output,
                }
            )
        return calls

    def _create_runtime(self) -> CoreRuntime:
        """Create runtime using the production Transactoid orchestrator."""
        mock_plaid = MockPlaidClient(self._db)
        transactoid = Transactoid(
            db=self._db,
            taxonomy=self._taxonomy,
            plaid_client=mock_plaid,  # type: ignore[arg-type]
        )
        return transactoid.create_runtime(sql_dialect="sqlite")
