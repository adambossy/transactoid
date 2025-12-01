from __future__ import annotations

import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
)
from promptorium import load_prompt
from pydantic import BaseModel
import yaml

from agents import Agent, ModelSettings, Runner, function_tool
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
        print()
        print(colorize(f"📞 Function call started: {name}()", "tool"))
        print(colorize("📝 Arguments: ", "args"), end="", flush=True)

    def on_tool_arguments_delta(self, call_id: str, delta: str) -> None:
        """Stream tool call arguments in magenta."""
        state = self.tool_calls.get(call_id)
        if not state:
            # Fallback: create if SDK omits start event before args stream
            state = ToolCallState(call_id, "unknown")
            self.tool_calls[call_id] = state
        state.args_chunks.append(delta)
        print(colorize(delta, "args"), end="", flush=True)

    def on_tool_call_completed(self, call_id: str) -> None:
        """Mark tool call as completed."""
        state = self.tool_calls.get(call_id)
        if state:
            self._clear_thinking()
            print()
            print(colorize(f"✅ Function call completed: {state.name}", "tool"))

    def on_tool_result(self, output: Any) -> None:
        """Display tool execution result in blue."""
        try:
            # Print compact, readable structure
            text = json.dumps(output, indent=2, ensure_ascii=False)
        except Exception:
            text = str(output)
        print(colorize("🡒 Tool result:\n", "out") + colorize(text, "out"))

    def on_message_output(self, item: MessageOutputItem) -> None:
        """Display final message output if needed."""
        msg = ItemHelpers.text_message_output(item)
        if msg:
            print(colorize(msg, "text"))

    def on_unknown(self, _event: Any) -> None:
        """Handle unknown events safely."""
        pass

    def end_turn(self, result: Any | None) -> None:
        """Complete the turn and optionally show token usage."""
        self._clear_thinking()
        if result is not None:
            raw_responses = getattr(result, "raw_responses", None)
            if raw_responses:
                print("\n=== TOKEN USAGE ===")
                for raw in raw_responses:
                    usage = getattr(raw, "usage", None)
                    if usage:
                        print(usage)
        print()


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

    # Replace placeholders
    rendered = template.replace("{{DATABASE_SCHEMA}}", schema_text)
    rendered = rendered.replace("{{CATEGORY_TAXONOMY}}", taxonomy_text)

    return rendered


async def run(
    *,
    db: DB | None = None,
    taxonomy: Taxonomy | None = None,
) -> None:
    """
    Run the interactive agent loop using OpenAI Agents SDK.

    The agent helps users understand and manage their personal finances
    through a conversational interface with access to transaction data.
    """
    # Initialize services
    if db is None:
        db_url = (
            os.environ.get("TRANSACTOID_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or "sqlite:///:memory:"
        )
        db = DB(db_url)

    if taxonomy is None:
        taxonomy = Taxonomy.from_db(db)

    # Load and render prompt template
    template = load_prompt("agent-loop")
    schema_hint = db.compact_schema_hint()
    taxonomy_dict = taxonomy.to_prompt()
    instructions = _render_prompt_template(
        template,
        database_schema=schema_hint,
        category_taxonomy=taxonomy_dict,
    )

    # Initialize tool dependencies
    persist_tool = PersistTool(db, taxonomy)

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
        # Note: db.run_sql requires model and pk_column, but for agent use
        # we'll need a simpler interface. For now, return empty results.
        # This should be enhanced to actually execute queries.
        return {"rows": [], "count": 0}

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
        try:
            plaid_client = PlaidClient.from_env()
        except PlaidClientError as e:
            return {
                "status": "error",
                "message": f"Failed to initialize Plaid client: {e}",
                "pages_processed": 0,
                "total_added": 0,
                "total_modified": 0,
                "total_removed": 0,
            }

        # Check if at least one account is connected
        plaid_items = db.list_plaid_items()
        if not plaid_items:
            # No accounts connected, trigger connection flow
            connection_result = plaid_client.connect_new_account(db=db)
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
            plaid_items = db.list_plaid_items()

        # Get the first Plaid item's access token
        # For now, sync the first item. In the future, could sync all items.
        plaid_item = plaid_items[0]
        access_token = plaid_item.access_token

        # Create categorizer
        categorizer = Categorizer(taxonomy)

        # Create sync tool
        sync_tool = SyncTool(
            plaid_client=plaid_client,
            categorizer=categorizer,
            db=db,
            taxonomy=taxonomy,
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

        Opens a browser window for the user to link their bank account via Plaid Link.
        The function handles the full OAuth flow, exchanges the public token for an
        access token, and stores the connection in the database.

        Returns:
            Dictionary with connection status including:
            - status: "success" or "error"
            - item_id: Plaid item ID if successful
            - institution_name: Institution name if available
            - message: Human-readable status message
        """
        try:
            client = PlaidClient.from_env()
        except PlaidClientError as e:
            return {
                "status": "error",
                "message": f"Failed to initialize Plaid client: {e}",
            }

        return client.connect_new_account(db=db)

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
        if not taxonomy.is_valid_key(new_category):
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
        result = persist_tool.apply_tags([], [tag])
        return {
            "applied": result.applied,
            "created_tags": result.created_tags,
            "status": "not_implemented",
            "message": "Tagging requires filter parsing",
        }

    # print("instructions:", instructions)

    # Create Agent instance
    agent = Agent(
        name="Transactoid",
        instructions=instructions,
        model="gpt-5",
        tools=[
            run_sql,
            sync_transactions,
            connect_new_account,
            update_category_for_transaction_groups,
            tag_transactions,
        ],
        model_settings=ModelSettings(reasoning_effort="medium", summary="detailed"),
    )

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

            # Run the agent with user input using the streaming API
            stream = Runner.run_streamed(
                agent,
                user_input,
            )

            # Use the orchestrator pattern with renderer and router
            renderer = StreamRenderer()
            router = EventRouter(renderer)

            renderer.begin_turn(user_input)

            async for event in stream.stream_events():
                router.handle(event)

            # Get final result if available
            final_result = None
            get_final_result = getattr(stream, "get_final_result", None)
            if callable(get_final_result):
                final_result = get_final_result()

            renderer.end_turn(final_result)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
