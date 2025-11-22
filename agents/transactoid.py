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
from services.db import DB
from services.taxonomy import Taxonomy
from tools.persist.persist_tool import PersistTool
import pprint

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


def to_recursive_dict(obj: Any, _seen: set[int] | None = None) -> Any:
    """
    Convert an object (and its attributes) into a structure of
    dicts/lists/primitives, following __dict__ recursively.
    """
    if _seen is None:
        _seen = set()

    obj_id = id(obj)
    if obj_id in _seen:
        # Prevent infinite recursion on cycles
        return f"<recursion: {type(obj).__name__}>"
    _seen.add(obj_id)

    # Primitives / already-serializable types
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj

    # Mapping types
    if isinstance(obj, dict):
        return {to_recursive_dict(k, _seen): to_recursive_dict(v, _seen) for k, v in obj.items()}

    # Iterable containers
    if isinstance(obj, (list, tuple, set, frozenset)):
        converted = [to_recursive_dict(item, _seen) for item in obj]
        return type(obj)(converted) if not isinstance(obj, set) else set(converted)

    # Objects with __dict__
    if hasattr(obj, "__dict__"):
        result = {"__class__": type(obj).__name__}
        for attr_name, value in vars(obj).items():
            result[attr_name] = to_recursive_dict(value, _seen)
        return result

    # Fallback: just use repr
    return repr(obj)


def pretty_print_event(event: Any) -> None:
    """
    Pretty-print an event object by recursively expanding its attributes.
    """
    data = to_recursive_dict(event)
    pprint.pprint(data, sort_dicts=False)


def concisely_print_event(event):
    event = to_recursive_dict(event)
    event_type = event["type"]

    # Default values
    seq = None
    content = None

    # Raw response events wrap another event
    if event_type == "raw_response_event":
        inner = event["data"]
        inner_type = inner["type"]
        seq = inner.get("sequence_number")

        # ----- CONTENT DECODING -----

        if inner_type == "response.function_call_arguments.delta":
            content = inner["delta"]

        elif inner_type == "response.function_call_arguments.done":
            content = inner["arguments"]

        elif inner_type == "response.output_text.delta":
            content = inner["delta"]

        elif inner_type == "response.output_text.done":
            content = inner["text"]

        elif inner_type == "response.content_part.done":
            content = inner["part"]["text"]

        elif inner_type == "response.completed":
            # gather all final message text segments
            outputs = inner["response"]["output"]
            content = []
            for out in outputs:
                if out["type"] == "message":
                    for part in out["content"]:
                        if "text" in part:
                            content.append(part["text"])

        # print result
        print(f"{inner_type} seq={seq} content={content}")

    # -------- RUN ITEM EVENTS --------

    elif event_type == "run_item_stream_event":
        name = event["name"]
        item = event["item"]

        if name == "tool_output":
            raw_output = item["raw_item"]["output"]
            content = raw_output

        elif name == "message_output_created":
            # final assistant message
            text_parts = []
            for part in item["raw_item"]["content"]:
                if "text" in part:
                    text_parts.append(part["text"])
            content = text_parts

        print(f"{name} content={content}")

    # -------- AGENT EVENTS --------

    elif event_type == "agent_updated_stream_event":
        print("agent_updated_stream_event")

    else:
        print(event_type)


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

            async for event in stream.stream_events():
                concisely_print_event(event)

        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
