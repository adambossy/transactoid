from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
import json
import sys
from typing import Any

from dotenv import load_dotenv
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
)
from promptorium import load_prompt
from pydantic import BaseModel
from sqlalchemy import text
import yaml

from agents import (
    Agent,
    ModelSettings,
    Runner,
    SQLiteSession,
    WebSearchTool,
    function_tool,
)
from agents.items import (
    ItemHelpers,
    MessageOutputItem,
    ToolCallOutputItem,
)
from services.db import DB
from services.plaid_client import PlaidClient, PlaidClientError
from services.taxonomy import Taxonomy
from tools.categorize.categorizer_tool import Categorizer
from tools.persist.persist_tool import PersistTool
from tools.sync.sync_tool import SyncTool

load_dotenv()


# Color and streaming helpers


def _use_color() -> bool:
    """Check if terminal supports color output."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


COLORS = {
    "reason": "33",  # yellow
    "text": "32",  # green
    "tool": "36",  # cyan
    "args": "35",  # magenta
    "out": "34",  # blue
    "error": "31",  # red
    "faint": "90",
}


def colorize(text: str, key: str) -> str:
    """Apply ANSI color codes to text if terminal supports it."""
    if not _use_color():
        return text
    code = COLORS.get(key, "0")
    return f"\033[{code}m{text}\033[0m"


class _JsonEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and other non-serializable types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class ToolCallState:
    """Track state for a streaming tool call."""

    def __init__(self, call_id: str, name: str) -> None:
        self.call_id = call_id
        self.name = name
        self.args_chunks: list[str] = []

    def args_text(self) -> str:
        """Get accumulated arguments as a single string."""
        return "".join(self.args_chunks)


class StreamRenderer:
    """Handle rendering of streaming events to the console."""

    def __init__(self) -> None:
        self.tool_calls: dict[str, ToolCallState] = {}
        self._spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_index = 0
        self._thinking_shown = False

    def begin_turn(self, user_input: str) -> None:
        """Start a new turn with user input."""
        print("")
        self._show_thinking()

    def _show_thinking(self) -> None:
        """Display thinking indicator."""
        char = self._spinner_chars[self._spinner_index % len(self._spinner_chars)]
        print(f"\r{colorize(f'{char} Thinking...', 'faint')}", end="", flush=True)
        self._thinking_shown = True
        self._spinner_index += 1

    def _clear_thinking(self) -> None:
        """Clear the thinking indicator."""
        if self._thinking_shown:
            print("\r" + " " * 20 + "\r", end="", flush=True)
            self._thinking_shown = False

    def on_reasoning(self, delta: str) -> None:
        """Stream reasoning text in yellow."""
        self._clear_thinking()
        print(colorize(delta, "reason"), end="", flush=True)

    def on_output_text(self, delta: str) -> None:
        """Stream output text in green."""
        self._clear_thinking()
        print(colorize(delta, "text"), end="", flush=True)

    def on_tool_call_started(self, call_id: str, name: str) -> None:
        """Begin a new tool call."""
        self.tool_calls[call_id] = ToolCallState(call_id, name)

    def on_tool_arguments_delta(self, call_id: str, delta: str) -> None:
        """Accumulate tool call arguments (printed on completion)."""
        state = self.tool_calls.get(call_id)
        if not state:
            state = ToolCallState(call_id, "unknown")
            self.tool_calls[call_id] = state
        state.args_chunks.append(delta)

    def on_tool_call_completed(self, call_id: str) -> None:
        """Print tool call with pretty-printed arguments."""
        state = self.tool_calls.get(call_id)
        if not state:
            return
        self._clear_thinking()
        args_text = state.args_text()
        if not args_text:
            print(colorize(f"📞 {state.name}()", "tool"))
        else:
            try:
                args = json.loads(args_text)
                if state.name == "run_sql" and "query" in args:
                    query = args.pop("query")
                    args_str = json.dumps(args) if args else "{}"
                    print(colorize(f"📞 {state.name}({args_str})", "tool"))
                    print(colorize("SQL:", "args"))
                    print(colorize(query, "args"))
                else:
                    args_str = json.dumps(args)
                    print(colorize(f"📞 {state.name}({args_str})", "tool"))
            except json.JSONDecodeError:
                print(colorize(f"📞 {state.name}({args_text})", "tool"))
        print()

    def _summarize_tool_result(self, output: Any) -> str:
        """Generate a brief summary of a tool result."""
        if not isinstance(output, dict):
            text = str(output)
            return text[:60] + "..." if len(text) > 60 else text

        parts = []
        if "status" in output:
            parts.append(output["status"])
        if "error" in output:
            error_text = str(output["error"])[:40]
            parts.append(f"error: {error_text}...")
        if "accounts" in output:
            parts.append(f"{len(output['accounts'])} accounts")
        if "count" in output:
            parts.append(f"{output['count']} rows")
        if "total_added" in output:
            parts.append(f"+{output['total_added']} txns")
        if "message" in output and "status" not in output:
            msg = output["message"][:40]
            parts.append(msg)

        return ", ".join(parts) if parts else "{...}"

    def on_tool_result(self, output: Any) -> None:
        """Display tool execution result in collapsed format with summary."""
        summary = self._summarize_tool_result(output)
        print(colorize(f"↩️ Tool result ▶ {summary}", "out"))
        print()

    def on_message_output(self, item: MessageOutputItem) -> None:
        """Display final message output if needed."""
        msg = ItemHelpers.text_message_output(item)
        if msg:
            print(colorize(msg, "text"))
            print()

    def on_unknown(self, _event: Any) -> None:
        """Handle unknown events safely."""
        pass

    def end_turn(self, result: Any | None) -> None:
        """Complete the turn and optionally show token usage."""
        self._clear_thinking()
        print()
        print()
        if result is not None:
            raw_responses = getattr(result, "raw_responses", None)
            if raw_responses:
                print("=== TOKEN USAGE ===")
                for raw in raw_responses:
                    usage = getattr(raw, "usage", None)
                    if usage:
                        print(usage)


class EventRouter:
    """Route SDK streaming events to appropriate renderer handlers."""

    def __init__(self, renderer: StreamRenderer) -> None:
        self.r = renderer
        # Track the latest call_id for SDKs that don't provide it on every args delta
        self._last_call_id: str | None = None

    def handle(self, event: Any) -> None:
        """Process a single streaming event."""
        et = getattr(event, "type", "")

        # Update spinner animation on each event while thinking
        if self.r._thinking_shown:
            self.r._show_thinking()

        # 1) Raw response events (reasoning, output text, function calls)
        if et == "raw_response_event":
            data = getattr(event, "data", None)
            if data is None:
                return

            dt = getattr(data, "type", "")

            # Reasoning summary text
            if dt == "response.reasoning_summary_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    self.r.on_reasoning(delta)
                return

            # Output text
            if dt == "response.output_text.delta":
                delta = getattr(data, "delta", None)
                if delta:
                    self.r.on_output_text(delta)
                return

        # 2) Raw response sub-events for function calls
        if et == "raw_response_event":
            data = getattr(event, "data", None)
            if isinstance(data, ResponseFunctionCallArgumentsDeltaEvent):
                call_id = (
                    getattr(data, "call_id", None) or self._last_call_id or "unknown"
                )
                self.r.on_tool_arguments_delta(call_id, data.delta or "")
                return

            # Detect start/end of function call output items
            dt = getattr(data, "type", "")
            item = getattr(data, "item", None)

            if (
                dt == "response.output_item.added"
                and getattr(item, "type", "") == "function_call"
            ):
                name = getattr(item, "name", "unknown")
                call_id = getattr(item, "call_id", "unknown")
                self._last_call_id = call_id
                self.r.on_tool_call_started(call_id, name)
                return

            if dt == "response.output_item.done":
                call_id = getattr(item, "call_id", None)
                if call_id:
                    self.r.on_tool_call_completed(call_id)
                    if self._last_call_id == call_id:
                        self._last_call_id = None
                return

        # 3) Runner item events (tool call exec + outputs)
        if et == "run_item_stream_event":
            item = getattr(event, "item", None)
            # ToolCallOutputItem: the tool procedure finished and returned output
            if isinstance(item, ToolCallOutputItem):
                self.r.on_tool_result(item.output)
                return
            # MessageOutputItem: optional final assistant message object
            if isinstance(item, MessageOutputItem):
                # Only use if you're not already printing output_text.delta
                # self.r.on_message_output(item)
                return

        # Ignore cosmetic updates
        if et == "agent_updated_stream_event":
            return

        # Unknown/unhandled
        self.r.on_unknown(event)


class TransactoidSession:
    """In-memory session for a Transactoid agent conversation."""

    def __init__(self, agent: Agent, session_id: str | None = None) -> None:
        sid = session_id or "transactoid_cli"
        self._agent = agent
        self._session_id = sid
        self._session = SQLiteSession(sid)

    async def run_turn(
        self,
        user_input: str,
        renderer: StreamRenderer,
        router: EventRouter,
    ) -> None:
        """Run a single streamed turn, reusing the same session for memory."""
        stream = Runner.run_streamed(
            self._agent,
            user_input,
            session=self._session,
        )

        renderer.begin_turn(user_input)

        async for event in stream.stream_events():
            router.handle(event)

        final_result = None
        get_final_result = getattr(stream, "get_final_result", None)
        if callable(get_final_result):
            final_result = get_final_result()

        renderer.end_turn(final_result)


class TransactionFilter(BaseModel):
    """Filter criteria for selecting transactions."""

    date_range: str | None = None
    category_prefix: str | None = None
    merchant: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None


def _render_prompt_template(
    template: str,
    *,
    database_schema: dict[str, Any],
    category_taxonomy: dict[str, Any],
) -> str:
    """Replace placeholders in the prompt template with actual data."""
    # Format database schema as readable text
    schema_text = yaml.dump(database_schema, default_flow_style=False, sort_keys=False)

    # Format taxonomy as readable text
    taxonomy_text = yaml.dump(
        category_taxonomy, default_flow_style=False, sort_keys=False
    )

    # Load taxonomy rules prompt
    taxonomy_rules = load_prompt("taxonomy-rules")

    # Replace placeholders
    rendered = template.replace("{{DATABASE_SCHEMA}}", schema_text)
    rendered = rendered.replace("{{CATEGORY_TAXONOMY}}", taxonomy_text)
    rendered = rendered.replace("{{TAXONOMY_RULES}}", taxonomy_rules)

    return rendered


class Transactoid:
    """Agent for helping users understand and manage their personal finances."""

    def __init__(
        self,
        *,
        db: DB,
        taxonomy: Taxonomy,
        plaid_client: PlaidClient | None = None,
    ) -> None:
        """Initialize the Transactoid agent.

        Args:
            db: Database instance
            taxonomy: Taxonomy instance for categorization
            plaid_client: Optional PlaidClient instance. If None, will be
                created from env when needed.
        """
        self._db = db
        self._taxonomy = taxonomy
        self._categorizer = Categorizer(taxonomy)
        self._persist_tool = PersistTool(db, taxonomy)
        self._plaid_client = plaid_client

    def _ensure_plaid_client(
        self, *, error_factory: Callable[[PlaidClientError], dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Ensure PlaidClient is initialized, returning error dict on failure.

        Args:
            error_factory: Callable that takes an exception and returns error dict

        Returns:
            None on success, error dict on failure
        """
        if self._plaid_client is None:
            try:
                self._plaid_client = PlaidClient.from_env()
            except PlaidClientError as e:
                return error_factory(e)
        return None

    async def run(self) -> None:
        """
        Run the interactive agent loop using OpenAI Agents SDK.

        The agent helps users understand and manage their personal finances
        through a conversational interface with access to transaction data.
        """
        # Load and render prompt template
        template = load_prompt("agent-loop")
        schema_hint = self._db.compact_schema_hint()
        taxonomy_dict = self._taxonomy.to_prompt()
        instructions = _render_prompt_template(
            template,
            database_schema=schema_hint,
            category_taxonomy=taxonomy_dict,
        )

        # Create tool wrapper functions
        @function_tool
        def run_sql(query: str) -> dict[str, Any]:
            """
            Execute SQL queries against the transaction database.

            Args:
                query: SQL query string to execute

            Returns:
                Dictionary with 'rows' (list of dicts) and 'count' (number of rows)
            """
            try:
                with self._db.session() as session:
                    result = session.execute(text(query))

                    if result.returns_rows:
                        # Convert Row objects to dicts
                        rows = [dict(row._mapping) for row in result.fetchall()]
                        # Convert date/datetime objects to strings for JSON
                        # serialization
                        for row in rows:
                            for key, value in row.items():
                                if hasattr(value, "isoformat"):
                                    row[key] = value.isoformat()
                        return {"rows": rows, "count": len(rows)}
                    else:
                        return {"rows": [], "count": result.rowcount}
            except Exception as e:
                return {"rows": [], "count": 0, "error": str(e)}

        @function_tool
        def sync_transactions() -> dict[str, Any]:
            """
            Trigger synchronization with Plaid to fetch latest transactions.

            Syncs all available transactions with automatic pagination, categorizes
            each page as it's fetched, and persists results to the database.

            Returns:
                Dictionary with sync status and summary including:
                - pages_processed: Number of pages synced
                - total_added: Total transactions added
                - total_modified: Total transactions modified
                - total_removed: Total transactions removed
                - status: "success" or "error"
            """
            # Get or create PlaidClient
            error = self._ensure_plaid_client(
                error_factory=lambda e: {
                    "status": "error",
                    "message": f"Failed to initialize Plaid client: {e}",
                    "pages_processed": 0,
                    "total_added": 0,
                    "total_modified": 0,
                    "total_removed": 0,
                }
            )
            if error is not None:
                return error

            # Check if at least one account is connected
            plaid_items = self._db.list_plaid_items()
            if not plaid_items:
                # No accounts connected, trigger connection flow
                connection_result = self._plaid_client.connect_new_account(db=self._db)
                if connection_result.get("status") != "success":
                    return {
                        "status": "error",
                        "message": (
                            "No accounts connected and failed to connect new account: "
                            f"{connection_result.get('message', 'Unknown error')}"
                        ),
                        "pages_processed": 0,
                        "total_added": 0,
                        "total_modified": 0,
                        "total_removed": 0,
                    }
                # Refresh the list after connection
                plaid_items = self._db.list_plaid_items()

            # Get the first Plaid item's access token
            # For now, sync the first item. In the future, could sync all items.
            plaid_item = plaid_items[0]
            access_token = plaid_item.access_token

            # Create sync tool using instance variables
            sync_tool = SyncTool(
                plaid_client=self._plaid_client,
                categorizer=self._categorizer,
                db=self._db,
                taxonomy=self._taxonomy,
                access_token=access_token,
                cursor=None,  # Start fresh sync
            )

            # Execute sync
            results = sync_tool.sync()

            # Aggregate results
            total_added = sum(len(r.categorized_added) for r in results)
            total_modified = sum(len(r.categorized_modified) for r in results)
            total_removed = sum(len(r.removed_transaction_ids) for r in results)

            return {
                "status": "success",
                "pages_processed": len(results),
                "total_added": total_added,
                "total_modified": total_modified,
                "total_removed": total_removed,
            }

        @function_tool
        def connect_new_account() -> dict[str, Any]:
            """
            Trigger UI flow for connecting a new bank/institution via Plaid.

            Opens a browser window for the user to link their bank account
            via Plaid Link. The function handles the full OAuth flow,
            exchanges the public token for an access token, and stores the
            connection in the database.

            Returns:
                Dictionary with connection status including:
                - status: "success" or "error"
                - item_id: Plaid item ID if successful
                - institution_name: Institution name if available
                - message: Human-readable status message
            """
            # Get or create PlaidClient
            error = self._ensure_plaid_client(
                error_factory=lambda e: {
                    "status": "error",
                    "message": f"Failed to initialize Plaid client: {e}",
                }
            )
            if error is not None:
                return error

            return self._plaid_client.connect_new_account(db=self._db)

        @function_tool
        def list_accounts() -> dict[str, Any]:
            """
            List all connected bank accounts from Plaid items.

            Returns account details for all connected institutions, including
            account names, types, and institution information.

            Returns:
                Dictionary with account listing status including:
                - status: "success" or "error"
                - accounts: List of account dictionaries with account and institution details
                - message: Human-readable status message
            """
            # Get or create PlaidClient
            error = self._ensure_plaid_client(
                error_factory=lambda e: {
                    "status": "error",
                    "accounts": [],
                    "message": f"Failed to initialize Plaid client: {e}",
                }
            )
            if error is not None:
                return error

            return self._plaid_client.list_accounts(db=self._db)

        @function_tool
        def update_category_for_transaction_groups(
            filter: TransactionFilter,
            new_category: str,
        ) -> dict[str, Any]:
            """
            Update categories for groups of transactions matching specified criteria.

            Args:
                filter: Dictionary with filter criteria (e.g., date_range, category_prefix)
                new_category: Category key to apply (must be valid from taxonomy)

            Returns:
                Dictionary with update summary
            """
            if not self._taxonomy.is_valid_key(new_category):
                return {
                    "error": f"Invalid category key: {new_category}",
                    "updated": 0,
                }

            # Note: This is a simplified implementation.
            # The actual implementation should parse the filter and update transactions.
            return {
                "status": "not_implemented",
                "message": "Bulk category update requires filter parsing",
                "category": new_category,
            }

        @function_tool
        def tag_transactions(
            filter: TransactionFilter,
            tag: str,
        ) -> dict[str, Any]:
            """
            Apply user-defined tags to transactions matching specified criteria.

            Args:
                filter: Filter criteria for selecting transactions
                tag: Tag name to apply

            Returns:
                Dictionary with tagging summary
            """
            # Note: This is a simplified implementation.
            # The actual implementation should parse the filter and apply tags.
            result = self._persist_tool.apply_tags([], [tag])
            return {
                "applied": result.applied,
                "created_tags": result.created_tags,
                "status": "not_implemented",
                "message": "Tagging requires filter parsing",
            }

        # Create Agent instance
        agent = Agent(
            name="Transactoid",
            instructions=instructions,
            model="gpt-5.1",
            tools=[
                run_sql,
                sync_transactions,
                connect_new_account,
                list_accounts,
                update_category_for_transaction_groups,
                tag_transactions,
                WebSearchTool(),
            ],
            model_settings=ModelSettings(reasoning_effort="medium", summary="detailed"),
        )

        # Create session for conversation memory
        session = TransactoidSession(agent)

        # Interactive loop
        print("Transactoid Agent - Personal Finance Assistant")
        print("Type 'exit' or 'quit' to end the session.\n")

        while True:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit"):
                    print("Goodbye!")
                    break

                renderer = StreamRenderer()
                router = EventRouter(renderer)

                await session.run_turn(user_input, renderer, router)

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
