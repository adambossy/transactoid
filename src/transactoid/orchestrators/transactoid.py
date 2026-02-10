from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ModelSettings,
    WebSearchTool,
    function_tool,
)
from dotenv import load_dotenv
from openai.types.shared import Reasoning
from pydantic import BaseModel
import yaml

from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.prompts.loader import load_transactoid_prompt
from transactoid.taxonomy.core import Taxonomy
from transactoid.tools.amazon.scraper import scrape_with_playwriter
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.migrate.migration_tool import MigrationTool
from transactoid.tools.persist.persist_tool import (
    PersistTool,
)
from transactoid.tools.sync.sync_tool import SyncTool

load_dotenv()


class TargetCategory(BaseModel):
    """Target category for split operations."""

    key: str
    name: str
    description: str | None = None


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
    taxonomy_rules = load_transactoid_prompt("taxonomy-rules")

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
        self._migration_tool = MigrationTool(db, taxonomy, self._categorizer)
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
        template = load_transactoid_prompt("agent-loop")
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
        async def sync_transactions() -> dict[str, Any]:
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
                    "items_synced": 0,
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
                        "items_synced": 0,
                        "total_added": 0,
                        "total_modified": 0,
                        "total_removed": 0,
                    }

            # SyncTool handles all items, cursor persistence, and Amazon mutations
            sync_tool = SyncTool(
                plaid_client=self._plaid_client,
                categorizer_factory=lambda: self._categorizer,
                db=self._db,
                taxonomy=self._taxonomy,
            )

            summary = await sync_tool.sync()
            return {"status": "success", **summary.to_dict()}

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
        def recategorize_merchant(
            merchant_id: int,
            category_key: str,
        ) -> dict[str, Any]:
            """
            Recategorize all transactions for a specific merchant.

            Args:
                merchant_id: The merchant ID to recategorize
                category_key: The new category key (e.g., "food.groceries")

            Returns:
                Dictionary with recategorization results
            """
            if not self._taxonomy.is_valid_key(category_key):
                return {
                    "status": "error",
                    "error": f"Invalid category key: {category_key}",
                    "updated": 0,
                }

            try:
                updated = self._persist_tool.recategorize_merchant(
                    merchant_id, category_key
                )
                return {
                    "status": "success",
                    "updated": updated,
                    "message": f"Recategorized {updated} transactions",
                }
            except ValueError as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "updated": 0,
                }

        @function_tool
        def tag_transactions(
            transaction_ids: list[int],
            tags: list[str],
        ) -> dict[str, Any]:
            """
            Apply tags to specific transactions.

            Args:
                transaction_ids: List of transaction IDs to tag
                tags: List of tag names to apply

            Returns:
                Dictionary with tagging results
            """
            result = self._persist_tool.apply_tags(transaction_ids, tags)
            return {
                "status": "success",
                "applied": result.applied,
                "created_tags": result.created_tags,
                "message": f"Applied {len(tags)} tags to {result.applied} transactions",
            }

        @function_tool
        def migrate_taxonomy(
            operation: str,
            source_key: str | None = None,
            target_key: str | None = None,
            source_keys: list[str] | None = None,
            targets: list[TargetCategory] | None = None,
            new_key: str | None = None,
            name: str | None = None,
            parent_key: str | None = None,
            description: str | None = None,
            fallback_key: str | None = None,
            recategorize: bool = False,
        ) -> dict[str, Any]:
            """
            Perform taxonomy migrations: rename, merge, split, add, or remove.

            Operations:
            - add: Add new category (key, name, parent_key, description)
            - remove: Remove category (source_key, fallback_key if has txns)
            - rename: Rename category (source_key, new_key)
            - merge: Merge categories (source_keys, target_key, recategorize)
            - split: Split category (source_key, targets list)

            When transactions are recategorized:
            - Verified with confidence >= 0.70 keep verified status
            - Verified with confidence < 0.70 are demoted to unverified

            Args:
                operation: One of "add", "remove", "rename", "merge", "split"
                source_key: Key of category to modify (remove/rename/split)
                target_key: Target category key (merge)
                source_keys: List of source keys (merge)
                targets: List of {key, name, description} dicts (split)
                new_key: New key name (rename)
                name: Display name (add)
                parent_key: Parent category key (add)
                description: Category description (add)
                fallback_key: Fallback for reassignment (remove)
                recategorize: Run LLM recategorization (merge)

            Returns:
                Migration result with success status and summary
            """
            if operation == "add":
                if not new_key or not name:
                    return {"success": False, "error": "add requires key and name"}
                result = self._migration_tool.add_category(
                    new_key, name, parent_key, description
                )
            elif operation == "remove":
                if not source_key:
                    return {"success": False, "error": "remove requires source_key"}
                result = self._migration_tool.remove_category(source_key, fallback_key)
            elif operation == "rename":
                if not source_key or not new_key:
                    return {
                        "success": False,
                        "error": "rename requires source_key and new_key",
                    }
                result = self._migration_tool.rename_category(source_key, new_key)
            elif operation == "merge":
                if not source_keys or not target_key:
                    return {
                        "success": False,
                        "error": "merge requires source_keys and target_key",
                    }
                result = self._migration_tool.merge_categories(
                    source_keys, target_key, recategorize=recategorize
                )
            elif operation == "split":
                if not source_key or not targets:
                    return {
                        "success": False,
                        "error": "split requires source_key and targets",
                    }
                target_tuples: list[tuple[str, str, str | None]] = [
                    (t.key, t.name, t.description) for t in targets
                ]
                result = self._migration_tool.split_category(source_key, target_tuples)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}

            return {
                "success": result.success,
                "operation": result.operation,
                "affected_transactions": result.affected_transaction_count,
                "recategorized": result.recategorized_count,
                "verified_retained": result.verified_retained_count,
                "verified_demoted": result.verified_demoted_count,
                "errors": result.errors,
                "summary": result.summary,
            }

        @function_tool
        def scrape_amazon_orders() -> dict[str, Any]:
            """
            Scrape Amazon order history using browser automation.

            This tool guides you through logging into Amazon in your browser,
            then uses browser automation to scrape your order history and
            save it to the database.

            Prerequisites:
            1. Open Chrome and navigate to https://www.amazon.com
            2. Log in to your Amazon account
            3. Click the Playwriter extension icon in your browser toolbar

            Returns:
                Dictionary with scrape status and summary including:
                - status: "success", "error", or "cancelled"
                - orders_created: Number of orders scraped
                - items_created: Number of items scraped
            """
            print(
                """
=== Amazon Order Scraping Setup ===

1. Open Chrome and navigate to https://www.amazon.com
2. Log in to your Amazon account
3. Click the Playwriter extension icon in your browser toolbar
4. When ready, type 'continue' to proceed with scraping
"""
            )

            user_input = input("Type 'continue' when ready: ").strip().lower()
            if user_input != "continue":
                return {"status": "cancelled", "message": "Scraping cancelled by user"}

            return scrape_with_playwriter(self._db)

        # Create Agent instance
        return Agent(
            name="Transactoid",
            instructions=instructions,
            model="gpt-5.2",
            tools=[
                run_sql,
                sync_transactions,
                connect_new_account,
                list_accounts,
                recategorize_merchant,
                tag_transactions,
                migrate_taxonomy,
                scrape_amazon_orders,
                WebSearchTool(),
            ],
            model_settings=ModelSettings(
                reasoning=Reasoning(effort="medium", summary="auto"), verbosity="high"
            ),
        )
