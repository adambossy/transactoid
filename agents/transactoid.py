from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any

try:  # pragma: no cover - handled at runtime
    from openai.agents import Agent, Runner, function_tool

    HAS_OPENAI_AGENTS = True
except ImportError:  # pragma: no cover - handled at runtime
    HAS_OPENAI_AGENTS = False

    Agent = object  # type: ignore[assignment]
    Runner = object  # type: ignore[assignment]

    def function_tool(func: Any | None = None, **_: Any):  # type: ignore[override]
        """
        Fallback decorator that becomes a no-op when the OpenAI Agents SDK
        is unavailable.
        """

        def _decorator(real_func: Any) -> Any:
            return real_func

        if callable(func):
            return func
        return _decorator


from services.db import DB
from services.plaid_client import PlaidClient
from services.taxonomy import Taxonomy
from tools.categorize.categorizer_tool import CategorizedTransaction, Categorizer
from tools.persist.persist_tool import ApplyTagsOutcome, PersistTool, SaveOutcome
from tools.sync.sync_tool import SyncTool

DATABASE_SCHEMA_PLACEHOLDER = "{{DATABASE_SCHEMA}}"
CATEGORY_TAXONOMY_PLACEHOLDER = "{{CATEGORY_TAXONOMY}}"
LOGGER = logging.getLogger(__name__)


@dataclass
class SyncRuntime:
    """
    Thin state container for Plaid syncs so consecutive tool calls preserve cursors.
    """

    plaid_client: PlaidClient
    categorizer: Categorizer
    access_token: str | None
    cursor: str | None = None

    def sync(self, *, count: int) -> tuple[list[CategorizedTransaction], str]:
        if not self.access_token:
            raise RuntimeError(
                "PLAID_ACCESS_TOKEN is not configured; "
                "set it before calling sync_transactions."
            )

        sync_tool = SyncTool(
            self.plaid_client,
            self.categorizer,
            access_token=self.access_token,
            cursor=self.cursor,
        )
        categorized, next_cursor = sync_tool.sync(count=count)
        self.cursor = next_cursor or self.cursor
        return categorized, next_cursor


def run(*, db: DB | None = None, taxonomy: Taxonomy | None = None) -> None:
    """
    Launch the Transactoid agent loop backed by the OpenAI Agents SDK.
    """

    if not HAS_OPENAI_AGENTS:
        raise RuntimeError(
            "The OpenAI Agents SDK is not installed. Install the `openai-agents` "
            "package or upgrade the `openai` library to a build that exposes "
            "`openai.agents`."
        )

    db_instance = db or _create_db_from_env()
    taxonomy_instance = taxonomy or Taxonomy.from_db(db_instance)
    prompt = _render_prompt(db_instance, taxonomy_instance)

    persist_tool = PersistTool(db_instance, taxonomy_instance)
    plaid_client = _create_plaid_client()
    categorizer = _create_categorizer(taxonomy_instance)
    sync_runtime = SyncRuntime(
        plaid_client=plaid_client,
        categorizer=categorizer,
        access_token=os.getenv("PLAID_ACCESS_TOKEN"),
        cursor=os.getenv("PLAID_STARTING_CURSOR"),
    )

    tools = _build_tools(
        db=db_instance,
        taxonomy=taxonomy_instance,
        persist_tool=persist_tool,
        sync_runtime=sync_runtime,
        plaid_client=plaid_client,
    )

    agent_model = os.getenv("TRANSACTOID_AGENT_MODEL", "gpt-4.1")
    agent = Agent(
        name="Transactoid",
        instructions=prompt,
        tools=tools,
        model=agent_model,
    )

    _interactive_loop(agent)


def _interactive_loop(agent: Agent) -> None:  # type: ignore[valid-type]
    """
    Simple REPL that forwards user questions to the agent runner until exit.
    """

    print("Transactoid agent ready. Type 'exit' or 'quit' to stop.")
    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Transactoid.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        try:
            result = Runner.run_sync(agent, user_input)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - conversational UX
            print(f"[agent-error] {exc}")
            continue

        output_text = _final_output_as_text(result.final_output)
        print(f"Transactoid> {output_text}")


def _build_tools(
    *,
    db: DB,
    taxonomy: Taxonomy,
    persist_tool: PersistTool,
    sync_runtime: SyncRuntime,
    plaid_client: PlaidClient,
) -> list[Any]:
    """
    Create OpenAI function tools that wrap core services.
    """

    @function_tool  # type: ignore[misc]
    def run_sql(query: str) -> dict[str, Any]:
        """
        Execute a read-only SQL query against the transaction database.

        Args:
            query: SELECT/WITH/EXPLAIN SQL statement to run.
        """

        _ensure_read_only_query(query)
        pk_column = os.getenv("TRANSACTOID_RUN_SQL_PK_COLUMN", "transaction_id")
        rows = db.run_sql(query, model=dict, pk_column=pk_column)
        serialized = [_serialize_value(row) for row in rows]
        return {"row_count": len(serialized), "rows": serialized}

    @function_tool  # type: ignore[misc]
    def sync_transactions(count: int = 500) -> dict[str, Any]:
        """
        Trigger a Plaid sync and return a summary of categorized transactions.

        Args:
            count: Maximum transactions to fetch this run.
        """

        categorized, next_cursor = sync_runtime.sync(count=count)
        persist_outcome = persist_tool.save_transactions(categorized)
        preview = [_categorized_txn_to_dict(txn) for txn in categorized[:5]]
        return {
            "fetched": len(categorized),
            "next_cursor": next_cursor,
            "preview": preview,
            "persist_summary": _summarize_save_outcome(persist_outcome),
        }

    @function_tool  # type: ignore[misc]
    def connect_new_account(user_identifier: str | None = None) -> dict[str, Any]:
        """
        Generate a Plaid Link token so the user can connect a new institution.

        Args:
            user_identifier: Optional override for the Plaid user ID. Defaults
                to the environment configuration.
        """

        user_id = user_identifier or os.getenv("PLAID_LINK_USER_ID", "transactoid-user")
        redirect_uri = os.getenv("PLAID_REDIRECT_URI")
        token = plaid_client.create_link_token(
            user_id=user_id, redirect_uri=redirect_uri
        )
        return {"link_token": token, "user_id": user_id, "redirect_uri": redirect_uri}

    @function_tool  # type: ignore[misc]
    def update_category_for_transaction_groups(
        filter: dict[str, Any], new_category: str
    ) -> dict[str, Any]:
        """
        Bulk update transaction categories using supported filters.

        Args:
            filter: Supported keys: merchant_id, transaction_ids.
            new_category: Category key from the taxonomy to apply.
        """

        if not taxonomy.is_valid_key(new_category):
            raise ValueError(
                f"Category key '{new_category}' is not defined in the taxonomy."
            )

        merchant_id = filter.get("merchant_id")
        if merchant_id is None:
            raise ValueError(
                "filter.merchant_id is required for the current implementation."
            )

        updated = persist_tool.bulk_recategorize_by_merchant(merchant_id, new_category)
        return {"updated_rows": updated, "filter": filter, "category_key": new_category}

    @function_tool  # type: ignore[misc]
    def tag_transactions(filter: dict[str, Any], tag: str) -> dict[str, Any]:
        """
        Apply a tag to explicit transaction IDs.

        Args:
            filter: Must include 'transaction_ids' (list[int]) for this stub
                implementation.
            tag: Tag name to attach.
        """

        transaction_ids = filter.get("transaction_ids") or []
        if not transaction_ids:
            raise ValueError(
                "filter.transaction_ids must include at least one transaction ID."
            )

        outcome = persist_tool.apply_tags(transaction_ids, [tag])
        return {
            "tag": tag,
            "transaction_ids": transaction_ids,
            "result": _summarize_apply_tags_outcome(outcome),
        }

    return [
        run_sql,
        sync_transactions,
        connect_new_account,
        update_category_for_transaction_groups,
        tag_transactions,
    ]


def _render_prompt(db: DB, taxonomy: Taxonomy) -> str:
    base_template = _load_prompt_template()
    schema_hint = json.dumps(
        db.compact_schema_hint(),
        indent=2,
        sort_keys=True,
    )
    taxonomy_hint = json.dumps(
        taxonomy.to_prompt(),
        indent=2,
        sort_keys=True,
    )

    return base_template.replace(DATABASE_SCHEMA_PLACEHOLDER, schema_hint).replace(
        CATEGORY_TAXONOMY_PLACEHOLDER, taxonomy_hint
    )


def _load_prompt_template(prompt_key: str = "agent-loop") -> str:
    """
    Load the ReAct system prompt from Promptorium (when configured) with a
    file fallback.
    """

    try:
        from promptorium.services import PromptService
        from promptorium.storage.fs import FileSystemPromptStorage
        from promptorium.util.repo_root import find_repo_root
    except Exception:
        return _read_prompt_file()

    try:
        storage = FileSystemPromptStorage(find_repo_root())
        svc = PromptService(storage)
        content = str(svc.load_prompt(prompt_key))
        if content.strip():
            return content
    except Exception as exc:  # pragma: no cover - log and fallback
        LOGGER.debug(
            "Promptorium load failed for key '%s': %s. Falling back to file template.",
            prompt_key,
            exc,
        )

    return _read_prompt_file()


def _read_prompt_file() -> str:
    prompt_path = (
        Path(__file__).resolve().parent.parent / "prompts" / "agent_loop_prompt.md"
    )
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def _create_db_from_env() -> DB:
    db_url = (
        os.getenv("TRANSACTOID_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite:///:memory:"
    )
    return DB(db_url)


def _create_plaid_client() -> PlaidClient:
    client_id = os.getenv("PLAID_CLIENT_ID", "stub-client-id")
    secret = os.getenv("PLAID_SECRET", "stub-secret")
    env = os.getenv("PLAID_ENV", "sandbox")
    client_name = os.getenv("PLAID_CLIENT_NAME", "transactoid")
    products_env = os.getenv("PLAID_PRODUCTS", "")
    products = [p.strip() for p in products_env.split(",") if p.strip()]
    return PlaidClient(
        client_id=client_id,
        secret=secret,
        env=env,  # type: ignore[arg-type]
        client_name=client_name,
        products=products or None,
    )


def _create_categorizer(taxonomy: Taxonomy) -> Categorizer:
    prompt_key = os.getenv(
        "TRANSACTOID_CATEGORIZER_PROMPT_KEY", "categorize-transactions"
    )
    model = os.getenv("TRANSACTOID_CATEGORIZER_MODEL", "gpt-4.1-mini")
    threshold_env = os.getenv("TRANSACTOID_CATEGORIZER_CONFIDENCE")
    try:
        confidence = float(threshold_env) if threshold_env else 0.70
    except ValueError:
        confidence = 0.70

    return Categorizer(
        taxonomy,
        prompt_key=prompt_key,
        model=model,
        confidence_threshold=confidence,
    )


def _ensure_read_only_query(query: str) -> None:
    if not query.strip():
        raise ValueError("Query must not be empty.")
    allowed_prefixes = ("select", "with", "explain", "pragma")
    normalized = query.lstrip().split(maxsplit=1)[0].lower()
    if normalized not in allowed_prefixes:
        raise ValueError(
            "Only read-only SQL statements (SELECT/WITH/EXPLAIN/PRAGMA) are permitted."
        )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if is_dataclass(value):
        return _serialize_value(asdict(value))
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        return {k: _serialize_value(v) for k, v in vars(value).items()}
    return value


def _categorized_txn_to_dict(txn: CategorizedTransaction) -> dict[str, Any]:
    payload = asdict(txn)
    payload["txn"] = _serialize_value(payload.get("txn"))
    return payload


def _summarize_save_outcome(outcome: SaveOutcome) -> dict[str, Any]:
    data = asdict(outcome)
    data["rows"] = [_serialize_value(row) for row in data.get("rows", [])]
    return data


def _summarize_apply_tags_outcome(outcome: ApplyTagsOutcome) -> dict[str, Any]:
    return asdict(outcome)


def _final_output_as_text(final_output: Any) -> str:
    if final_output is None:
        return "[no response produced]"
    if isinstance(final_output, str):
        return final_output
    if isinstance(final_output, Iterable) and not isinstance(
        final_output, (dict, bytes)
    ):
        return "\n".join(str(chunk) for chunk in final_output)
    try:
        return json.dumps(final_output, indent=2, sort_keys=True)
    except Exception:
        return str(final_output)
