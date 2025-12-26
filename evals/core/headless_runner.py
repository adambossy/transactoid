from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from agents import Agent, ModelSettings, Runner, SQLiteSession, function_tool
from agents.items import MessageOutputItem, ToolCallOutputItem
from openai.types.shared.reasoning import Reasoning

from services.db import DB
from services.taxonomy import Taxonomy


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
        """Create agent with inline tools (same as production agent)."""

        # Define inline tools using function_tool decorator
        @function_tool
        def run_sql(query: str) -> dict[str, Any]:
            """Execute SQL query against transaction database.

            Args:
                query: SQL SELECT query to execute

            Returns:
                Dict with 'rows' (list of dicts) and 'count' (int)
            """
            # Execute query using DB.execute_raw_sql
            result = self._db.execute_raw_sql(query)

            # Convert result to list of dicts
            rows = []
            for row in result:
                # Convert row to dict using column names
                row_dict = {}
                for idx, col in enumerate(result.keys()):
                    row_dict[col] = row[idx]
                rows.append(row_dict)

            return {"rows": rows, "count": len(rows)}

        # Create agent with model settings
        return Agent(
            name="Transactoid",
            instructions="""You are a personal finance assistant that helps users analyze their transaction data.

You have access to a SQLite database with transaction data. Use the run_sql tool to query and analyze transactions.

IMPORTANT: This is SQLite, not PostgreSQL. Use SQLite syntax:
- Date functions: date(), datetime(), strftime(), julianday()
- Date comparisons: date(posted_at) >= date('now', '-1 month')
- NO PostgreSQL functions: date_trunc(), interval, CURRENT_DATE
- Example: Last month spending: WHERE date(posted_at) >= date('now', 'start of month', '-1 month')

When answering questions:
- Be concise and direct (1-3 sentences)
- Format currency as $X,XXX.XX
- Format percentages as XX%
- Use markdown tables for breakdowns
- Maintain a slightly snarky, sarcastic tone while being helpful

Database schema:
- transactions: transaction_id, external_id, source, account_id, posted_at, amount_cents, currency, merchant_descriptor, merchant_id, category_id, is_verified
- merchants: merchant_id, normalized_name, display_name
- categories: category_id, parent_id, key, name, description, parent_key
- tags: tag_id, name, description
- transaction_tags: transaction_id, tag_id

Remember:
- amount_cents is stored as integers (cents), convert to dollars by dividing by 100
- posted_at is stored as ISO8601 strings (YYYY-MM-DD HH:MM:SS)""",
            model="gpt-5.1",
            tools=[run_sql],
            model_settings=ModelSettings(reasoning=Reasoning(effort="medium")),
        )
