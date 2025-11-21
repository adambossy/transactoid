from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent, ResponseTextDeltaEvent
from promptorium import load_prompt
from pydantic import BaseModel
import yaml

from agents import Agent, ModelSettings, Runner, function_tool
from agents.items import (
    ItemHelpers,
    MessageOutputItem,
    ToolCallItem,
    ToolCallOutputItem,
    ReasoningItem,
)
from services.db import DB
from services.taxonomy import Taxonomy
from tools.persist.persist_tool import PersistTool

load_dotenv()


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

        Returns:
            Dictionary with sync status and summary
        """
        # Note: SyncTool requires PlaidClient, Categorizer, and access_token.
        # For now, return a placeholder response.
        # This should be enhanced to actually trigger sync.
        return {
            "status": "not_implemented",
            "message": "Sync functionality requires Plaid configuration",
        }

    @function_tool
    def connect_new_account() -> dict[str, Any]:
        """
        Trigger UI flow for connecting a new bank/institution via Plaid.

        Returns:
            Dictionary with connection status
        """
        return {
            "status": "not_implemented",
            "message": "Account connection requires Plaid Link integration",
        }

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

            print("\n=== STEP-BY-STEP TRACE ===")

            # Track the last assistant message in case the streaming
            # implementation does not expose a final aggregated result.
            last_assistant_message: Any | None = None
            function_calls: dict[Any, dict[str, Any]] = {}  # call_id -> {name, arguments}

            async for event in stream.stream_events():
                # Raw text
                if event.type == "raw_response_event" and not isinstance(event.data, ResponseTextDeltaEvent):
                    # print(f"Raw response: {event.raw_item.content}")
                    import pprint
                    pprint.pprint(event.data.__dict__)
                elif event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    print(event.data.delta, end="", flush=True)

                    # Function call started
                    if event.data.type == "response.output_item.added":
                        if getattr(event.data.item, "type", None) == "function_call":
                            function_name = getattr(event.data.item, "name", "unknown")
                            call_id = getattr(event.data.item, "call_id", "unknown")

                            function_calls[call_id] = {"name": function_name, "arguments": ""}
                            current_active_call_id = call_id
                            print(f"\n📞 Function call streaming started: {function_name}()")
                            print("📝 Arguments building...")

                    # Real-time argument streaming
                    elif isinstance(event.data, ResponseFunctionCallArgumentsDeltaEvent):
                        if current_active_call_id and current_active_call_id in function_calls:
                            function_calls[current_active_call_id]["arguments"] += event.data.delta
                            print(event.data.delta, end="", flush=True)

                    # Function call completed
                    elif event.data.type == "response.output_item.done":
                        if hasattr(event.data.item, "call_id"):
                            call_id = getattr(event.data.item, "call_id", "unknown")
                            if call_id in function_calls:
                                function_info = function_calls[call_id]
                                print(f"\n✅ Function call streaming completed: {function_info['name']}")
                                print()
                                if current_active_call_id == call_id:
                                    current_active_call_id = None

                elif event.type == "agent_updated_stream_event":
                    print(f"Agent updated: {event.new_agent.name}")
                    continue
                elif event.type == "run_item_stream_event":
                    if event.item.type == "tool_call_item":
                        print("-- Tool was called")
                    elif event.item.type == "tool_call_output_item":
                        print(f"-- Tool output: {event.item.output}")
                    elif event.item.type == "message_output_item":
                        print(f"-- Message output:\n {ItemHelpers.text_message_output(event.item)}")
                    elif event.item.type == "reasoning_item":
                        print("\n[REASONING]")
                        import pprint
                        pprint.pprint(event.item.__dict__)
                    else:
                        print(f"Unknown event type: {event.item.type}")
                        pass  # Ignore other event types

            # Prefer a final aggregated result from the streaming object
            # if it is available (mirrors the Agents SDK pattern); otherwise
            # fall back to the last assistant message we observed.
            # final_output: Any | None = None
            # get_final_result = getattr(stream, "get_final_result", None)
            # if callable(get_final_result):
            #     result = get_final_result()
            #     final_output = getattr(result, "final_output", None)

            #     # If we have the full result, also surface token usage when present.
            #     raw_responses = getattr(result, "raw_responses", None)
            #     if raw_responses is not None:
            #         print("\n=== TOKEN USAGE ===")
            #         for raw_response in raw_responses:
            #             usage = getattr(raw_response, "usage", None)
            #             if usage is not None:
            #                 print(usage)
            # else:
            #     final_output = last_assistant_message

            # print("\n=== FINAL OUTPUT ===")
            # if final_output is not None:
            #     print(final_output)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
