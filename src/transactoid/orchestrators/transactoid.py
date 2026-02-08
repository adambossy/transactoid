from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from agents import Agent
from dotenv import load_dotenv
from promptorium import load_prompt
from pydantic import BaseModel
import yaml

from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.db.facade import DB
from transactoid.core.runtime import (
    CoreRuntime,
    CoreRuntimeConfig,
    create_core_runtime,
    load_core_runtime_config_from_env,
)
from transactoid.core.runtime.openai_runtime import OpenAICoreRuntime
from transactoid.taxonomy.core import Taxonomy
from transactoid.tools.amazon.scraper import scrape_with_playwriter
from transactoid.tools.base import StandardTool
from transactoid.tools.categorize.categorizer_tool import Categorizer
from transactoid.tools.migrate.migration_tool import MigrationTool
from transactoid.tools.persist.persist_tool import PersistTool
from transactoid.tools.protocol import ToolInputSchema
from transactoid.tools.registry import ToolRegistry
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
    """Replace placeholders in the prompt template with actual data."""
    if sql_dialect == "sqlite":
        sql_directives_path = Path("src/transactoid/prompts/sql-directives/sqlite.md")
    else:
        sql_directives_path = Path(
            "src/transactoid/prompts/sql-directives/postgresql.md"
        )

    sql_directives = sql_directives_path.read_text()
    schema_text = yaml.dump(database_schema, default_flow_style=False, sort_keys=False)
    taxonomy_text = yaml.dump(
        category_taxonomy, default_flow_style=False, sort_keys=False
    )
    taxonomy_rules = load_prompt("taxonomy-rules")

    rendered = template.replace("{{DATABASE_SCHEMA}}", schema_text)
    rendered = rendered.replace("{{CATEGORY_TAXONOMY}}", taxonomy_text)
    rendered = rendered.replace("{{TAXONOMY_RULES}}", taxonomy_rules)
    rendered = rendered.replace("{{SQL_DIALECT_DIRECTIVES}}", sql_directives)
    return rendered


class _RunSqlTool(StandardTool):
    _name = "run_sql"
    _description = "Execute SQL queries against the transaction database."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL query string to execute",
            }
        },
        "required": ["query"],
    }

    def __init__(self, db: DB) -> None:
        self._db = db

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        try:
            result = self._db.execute_raw_sql(query)
            if result.returns_rows:
                rows = [dict(row._mapping) for row in result.fetchall()]
                for row in rows:
                    for key, value in row.items():
                        if hasattr(value, "isoformat"):
                            row[key] = value.isoformat()
                return {"rows": rows, "count": len(rows), "query": query}
            return {"rows": [], "count": result.rowcount, "query": query}
        except Exception as e:
            return {"rows": [], "count": 0, "error": str(e), "query": query}


class _SyncTransactionsTool(StandardTool):
    _name = "sync_transactions"
    _description = "Sync latest transactions from Plaid, categorize, and persist."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(
        self,
        *,
        ensure_plaid_client: Callable[
            [Callable[[PlaidClientError], dict[str, Any]]], dict[str, Any] | None
        ],
        get_plaid_client: Callable[[], PlaidClient],
        db: DB,
        taxonomy: Taxonomy,
        categorizer_factory: Callable[[], Categorizer],
    ) -> None:
        self._ensure_plaid_client = ensure_plaid_client
        self._get_plaid_client = get_plaid_client
        self._db = db
        self._taxonomy = taxonomy
        self._categorizer_factory = categorizer_factory

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        error = self._ensure_plaid_client(
            lambda e: {
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

        plaid_client = self._get_plaid_client()
        plaid_items = self._db.list_plaid_items()
        if not plaid_items:
            connection_result = plaid_client.connect_new_account(db=self._db)
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

        sync_tool = SyncTool(
            plaid_client=plaid_client,
            categorizer_factory=self._categorizer_factory,
            db=self._db,
            taxonomy=self._taxonomy,
        )
        summary = await sync_tool.sync()
        return {"status": "success", **summary.to_dict()}


class _ConnectNewAccountTool(StandardTool):
    _name = "connect_new_account"
    _description = "Connect a new bank account via Plaid Link flow."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(
        self,
        *,
        ensure_plaid_client: Callable[
            [Callable[[PlaidClientError], dict[str, Any]]], dict[str, Any] | None
        ],
        get_plaid_client: Callable[[], PlaidClient],
        db: DB,
    ) -> None:
        self._ensure_plaid_client = ensure_plaid_client
        self._get_plaid_client = get_plaid_client
        self._db = db

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        error = self._ensure_plaid_client(
            lambda e: {
                "status": "error",
                "message": f"Failed to initialize Plaid client: {e}",
            }
        )
        if error is not None:
            return error
        return self._get_plaid_client().connect_new_account(db=self._db)


class _ListAccountsTool(StandardTool):
    _name = "list_accounts"
    _description = "List all connected bank accounts from Plaid items."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(
        self,
        *,
        ensure_plaid_client: Callable[
            [Callable[[PlaidClientError], dict[str, Any]]], dict[str, Any] | None
        ],
        get_plaid_client: Callable[[], PlaidClient],
        db: DB,
    ) -> None:
        self._ensure_plaid_client = ensure_plaid_client
        self._get_plaid_client = get_plaid_client
        self._db = db

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        error = self._ensure_plaid_client(
            lambda e: {
                "status": "error",
                "accounts": [],
                "message": f"Failed to initialize Plaid client: {e}",
            }
        )
        if error is not None:
            return error
        return self._get_plaid_client().list_accounts(db=self._db)


class _RecategorizeMerchantTool(StandardTool):
    _name = "recategorize_merchant"
    _description = "Recategorize all transactions for a specific merchant."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "merchant_id": {
                "type": "integer",
                "description": "Merchant ID to recategorize",
            },
            "category_key": {
                "type": "string",
                "description": "Target category key",
            },
        },
        "required": ["merchant_id", "category_key"],
    }

    def __init__(self, persist_tool: PersistTool, taxonomy: Taxonomy) -> None:
        self._persist_tool = persist_tool
        self._taxonomy = taxonomy

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        merchant_id = int(kwargs["merchant_id"])
        category_key = str(kwargs["category_key"])

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


class _TagTransactionsTool(StandardTool):
    _name = "tag_transactions"
    _description = "Apply tags to specific transactions."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "transaction_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Transaction IDs",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tag names",
            },
        },
        "required": ["transaction_ids", "tags"],
    }

    def __init__(self, persist_tool: PersistTool) -> None:
        self._persist_tool = persist_tool

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        transaction_ids = [int(tx_id) for tx_id in kwargs["transaction_ids"]]
        tags = [str(tag) for tag in kwargs["tags"]]
        result = self._persist_tool.apply_tags(transaction_ids, tags)
        return {
            "status": "success",
            "applied": result.applied,
            "created_tags": result.created_tags,
            "message": f"Applied {len(tags)} tags to {result.applied} transactions",
        }


class _MigrateTaxonomyTool(StandardTool):
    _name = "migrate_taxonomy"
    _description = "Perform taxonomy migrations: add, remove, rename, merge, split."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "description": "Migration operation"},
            "source_key": {"type": "string", "description": "Source key"},
            "target_key": {"type": "string", "description": "Target key"},
            "source_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Source keys for merge",
            },
            "targets": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Split targets",
            },
            "new_key": {"type": "string", "description": "New key"},
            "name": {"type": "string", "description": "Display name"},
            "parent_key": {"type": "string", "description": "Parent key"},
            "description": {"type": "string", "description": "Description"},
            "fallback_key": {"type": "string", "description": "Fallback key"},
            "recategorize": {"type": "boolean", "description": "Recategorize"},
        },
        "required": ["operation"],
    }

    def __init__(self, migration_tool: MigrationTool) -> None:
        self._migration_tool = migration_tool

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        operation = str(kwargs.get("operation", ""))
        source_key = kwargs.get("source_key")
        target_key = kwargs.get("target_key")
        source_keys = kwargs.get("source_keys")
        targets = kwargs.get("targets")
        new_key = kwargs.get("new_key")
        name = kwargs.get("name")
        parent_key = kwargs.get("parent_key")
        description = kwargs.get("description")
        fallback_key = kwargs.get("fallback_key")
        recategorize = bool(kwargs.get("recategorize", False))

        if operation == "add":
            if not new_key or not name:
                return {"success": False, "error": "add requires key and name"}
            result = self._migration_tool.add_category(
                str(new_key),
                str(name),
                _str_or_none(parent_key),
                _str_or_none(description),
            )
        elif operation == "remove":
            if not source_key:
                return {"success": False, "error": "remove requires source_key"}
            result = self._migration_tool.remove_category(
                str(source_key), _str_or_none(fallback_key)
            )
        elif operation == "rename":
            if not source_key or not new_key:
                return {
                    "success": False,
                    "error": "rename requires source_key and new_key",
                }
            result = self._migration_tool.rename_category(str(source_key), str(new_key))
        elif operation == "merge":
            if not source_keys or not target_key:
                return {
                    "success": False,
                    "error": "merge requires source_keys and target_key",
                }
            merge_source_keys = [str(value) for value in source_keys]
            result = self._migration_tool.merge_categories(
                merge_source_keys,
                str(target_key),
                recategorize=recategorize,
            )
        elif operation == "split":
            if not source_key or not targets:
                return {
                    "success": False,
                    "error": "split requires source_key and targets",
                }
            target_models = [
                TargetCategory.model_validate(target) for target in targets
            ]
            target_tuples: list[tuple[str, str, str | None]] = [
                (item.key, item.name, item.description) for item in target_models
            ]
            result = self._migration_tool.split_category(str(source_key), target_tuples)
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


class _ScrapeAmazonOrdersTool(StandardTool):
    _name = "scrape_amazon_orders"
    _description = "Scrape Amazon order history with browser automation."
    _input_schema: ToolInputSchema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, db: DB) -> None:
        self._db = db

    async def _execute_impl(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
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


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


class Transactoid:
    """Agent orchestrator for personal finance workflows."""

    def __init__(
        self,
        *,
        db: DB,
        taxonomy: Taxonomy,
        plaid_client: PlaidClient | None = None,
    ) -> None:
        self._db = db
        self._taxonomy = taxonomy
        self._categorizer = Categorizer(taxonomy)
        self._persist_tool = PersistTool(db, taxonomy)
        self._migration_tool = MigrationTool(db, taxonomy, self._categorizer)
        self._plaid_client = plaid_client

    def _ensure_plaid_client(
        self, *, error_factory: Callable[[PlaidClientError], dict[str, Any]]
    ) -> dict[str, Any] | None:
        if self._plaid_client is None:
            try:
                self._plaid_client = PlaidClient.from_env()
            except PlaidClientError as e:
                return error_factory(e)
        return None

    def _get_plaid_client(self) -> PlaidClient:
        if self._plaid_client is None:
            raise RuntimeError("Plaid client not initialized")
        return self._plaid_client

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(_RunSqlTool(self._db))
        registry.register(
            _SyncTransactionsTool(
                ensure_plaid_client=lambda error_factory: self._ensure_plaid_client(
                    error_factory=error_factory
                ),
                get_plaid_client=self._get_plaid_client,
                db=self._db,
                taxonomy=self._taxonomy,
                categorizer_factory=lambda: self._categorizer,
            )
        )
        registry.register(
            _ConnectNewAccountTool(
                ensure_plaid_client=lambda error_factory: self._ensure_plaid_client(
                    error_factory=error_factory
                ),
                get_plaid_client=self._get_plaid_client,
                db=self._db,
            )
        )
        registry.register(
            _ListAccountsTool(
                ensure_plaid_client=lambda error_factory: self._ensure_plaid_client(
                    error_factory=error_factory
                ),
                get_plaid_client=self._get_plaid_client,
                db=self._db,
            )
        )
        registry.register(_RecategorizeMerchantTool(self._persist_tool, self._taxonomy))
        registry.register(_TagTransactionsTool(self._persist_tool))
        registry.register(_MigrateTaxonomyTool(self._migration_tool))
        registry.register(_ScrapeAmazonOrdersTool(self._db))
        return registry

    def create_runtime(
        self,
        *,
        sql_dialect: str = "postgresql",
        runtime_config: CoreRuntimeConfig | None = None,
    ) -> CoreRuntime:
        """Create a provider-agnostic runtime with shared tools and prompts."""
        template = load_prompt("agent-loop")
        schema_hint = self._db.compact_schema_hint()
        taxonomy_dict = self._taxonomy.to_prompt()
        instructions = _render_prompt_template(
            template,
            database_schema=schema_hint,
            category_taxonomy=taxonomy_dict,
            sql_dialect=sql_dialect,
        )
        config = runtime_config or load_core_runtime_config_from_env()
        registry = self._build_tool_registry()
        return create_core_runtime(
            config=config,
            instructions=instructions,
            registry=registry,
        )

    def create_agent(self, sql_dialect: str = "postgresql") -> Agent:
        """Compatibility shim for legacy call sites that still expect Agent."""
        runtime = self.create_runtime(
            sql_dialect=sql_dialect,
            runtime_config=CoreRuntimeConfig(provider="openai", model="gpt-5.3"),
        )
        if not isinstance(runtime, OpenAICoreRuntime):
            raise RuntimeError("create_agent is only supported with OpenAI runtime")
        return cast(Agent, runtime.native_agent)
