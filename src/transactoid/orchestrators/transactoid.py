from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ModelSettings,
    Runner,
    SQLiteSession,
    WebSearchTool,
    function_tool,
)
from dotenv import load_dotenv
from openai.types.shared import Reasoning
from promptorium import load_prompt
from pydantic import BaseModel
import yaml

from transactoid.adapters.db.facade import DB
from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.taxonomy.core import Taxonomy
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.persist.persist_tool import (
    PersistTool,
)
from transactoid.tools.sync.sync_tool import SyncTool
from transactoid.ui.markdown_renderer import MarkdownStreamRenderer
from transactoid.ui.stream_renderer import EventRouter, StreamRenderer

load_dotenv()


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
    sql_dialect: str = "postgresql",
) -> str:
    """Replace placeholders in the prompt template with actual data.

    Args:
        template: Prompt template with {{VARIABLE}} placeholders
        database_schema: Database schema dict
        category_taxonomy: Category taxonomy dict
        sql_dialect: "postgresql" (default) or "sqlite"

    Returns:
        Rendered prompt with all placeholders replaced
    """
    # Load SQL dialect directives based on parameter
    if sql_dialect == "sqlite":
        sql_directives_path = Path("src/transactoid/prompts/sql-directives/sqlite.md")
    else:
        sql_directives_path = Path(
            "src/transactoid/prompts/sql-directives/postgresql.md"
        )

    sql_directives = sql_directives_path.read_text()

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
    rendered = rendered.replace("{{SQL_DIALECT_DIRECTIVES}}", sql_directives)

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

    def create_agent(self, sql_dialect: str = "postgresql") -> Agent:
        """
        Create and return the Transactoid Agent instance with all tools.

        Args:
            sql_dialect: SQL dialect for query generation ("postgresql" or "sqlite").
                Defaults to "postgresql" for production use.
                Evals pass "sqlite" to match their test database.

        Returns:
            Agent configured with all Transactoid tools and instructions
        """
        # Load and render prompt template
        template = load_prompt("agent-loop")
        schema_hint = self._db.compact_schema_hint()
        taxonomy_dict = self._taxonomy.to_prompt()
        instructions = _render_prompt_template(
            template,
            database_schema=schema_hint,
            category_taxonomy=taxonomy_dict,
            sql_dialect=sql_dialect,
        )

        # Create tool wrapper functions
        @function_tool
        def run_sql(query: str) -> dict[str, Any]:
            """
            Execute SQL queries against the transaction database.

            Args:
                query: SQL query string to execute

            Returns:
                Dictionary with 'rows' (list of dicts), 'count' (number of rows),
                and 'query' (the executed SQL)
            """
            try:
                result = self._db.execute_raw_sql(query)

                if result.returns_rows:
                    # Convert Row objects to dicts
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    # Convert date/datetime objects to strings for JSON
                    # serialization
                    for row in rows:
                        for key, value in row.items():
                            if hasattr(value, "isoformat"):
                                row[key] = value.isoformat()
                    return {"rows": rows, "count": len(rows), "query": query}
                else:
                    return {"rows": [], "count": result.rowcount, "query": query}
            except Exception as e:
                return {"rows": [], "count": 0, "error": str(e), "query": query}

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

            # After _ensure_plaid_client() returns None, _plaid_client is
            # guaranteed to be initialized
            assert self._plaid_client is not None  # noqa: S101

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

            # After _ensure_plaid_client() returns None, _plaid_client is
            # guaranteed to be initialized
            assert self._plaid_client is not None  # noqa: S101
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
                - accounts: List of account dictionaries with account and
                  institution details
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

            # After _ensure_plaid_client() returns None, _plaid_client is
            # guaranteed to be initialized
            assert self._plaid_client is not None  # noqa: S101
            return self._plaid_client.list_accounts(db=self._db)

        @function_tool
        def update_category_for_transaction_groups(
            filter: TransactionFilter,
            new_category: str,
        ) -> dict[str, Any]:
            """
            Update categories for groups of transactions matching specified criteria.

            Args:
                filter: Dictionary with filter criteria (e.g., date_range,
                    category_prefix)
                new_category: Category key to apply (must be valid from
                    taxonomy)

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
        return Agent(
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
            model_settings=ModelSettings(
                reasoning=Reasoning(effort="medium"), verbosity="high"
            ),
        )

    async def run(self) -> None:
        """
        Run the interactive agent loop using OpenAI Agents SDK.

        The agent helps users understand and manage their personal finances
        through a conversational interface with access to transaction data.
        """
        # Create agent using the extracted method
        agent = self.create_agent()

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

                renderer = MarkdownStreamRenderer()
                router = EventRouter(renderer)

                await session.run_turn(user_input, renderer, router)

            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
