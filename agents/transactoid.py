from __future__ import annotations

from typing import Any, Optional, TypedDict


def run(*, db: Any | None = None, taxonomy: Any | None = None) -> None:
    """
    Transactoid interactive agent loop using OpenAI Agents SDK primitives.
 
    Notes:
    - Imports for the Agents SDK are performed lazily to avoid import errors
      during test discovery if the SDK is not available.
    - Tool implementations are thin wrappers around local service stubs.
    """
    import os
    import sys
    import json
    from pathlib import Path
 
    # Lazy import to avoid import-time failures if not installed
    try:
        from openai.agents import Agent, Runner, function_tool  # type: ignore[attr-defined]
        _agents_available = True
    except Exception:
        # Fallback no-op decorator keeps signatures intact
        def function_tool(fn: Any) -> Any:  # type: ignore[no-redef]
            return fn
        Agent = None  # type: ignore[assignment]
        Runner = None  # type: ignore[assignment]
        _agents_available = False
 
    # Local imports for services (stubs in this repo)
    from services.db import DB
    from services.taxonomy import Taxonomy
    from tools.persist.persist_tool import PersistTool
 
    # -----------------------------
    # Helpers: prompt loading/render
    # -----------------------------
    def _load_agent_prompt_template() -> str:
        # Try promptorium first, then file fallback
        try:
            from promptorium import load_prompt  # type: ignore
            text = load_prompt("agent-loop")
            return str(text)
        except Exception:
            # Fallback to local file
            repo_root = Path(__file__).resolve().parent.parent
            prompt_path = repo_root / "prompts" / "agent_loop_prompt.md"
            return prompt_path.read_text(encoding="utf-8")
 
    def _render_instructions(
        template: str,
        *,
        db_obj: DB,
        taxonomy_obj: Taxonomy,
    ) -> str:
        # Serialize schema and taxonomy as readable JSON blocks
        schema_obj = db_obj.compact_schema_hint()
        taxonomy_payload = taxonomy_obj.to_prompt()
        schema_json = json.dumps(schema_obj, indent=2, sort_keys=True)
        taxonomy_json = json.dumps(taxonomy_payload, indent=2, sort_keys=True)
        rendered = (
            template.replace("{{DATABASE_SCHEMA}}", schema_json)
            .replace("{{CATEGORY_TAXONOMY}}", taxonomy_json)
        )
        return rendered
 
    # -----------------------------
    # Initialize services
    # -----------------------------
    if db is None:
        db_url = (
            os.getenv("TRANSACTOID_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or "sqlite:///:memory:"
        )
        db = DB(db_url)
    assert db is not None
 
    if taxonomy is None:
        taxonomy = Taxonomy.from_db(db)
    assert taxonomy is not None
 
    persist_tool = PersistTool(db=db, taxonomy=taxonomy)
 
    # -----------------------------
    # Tool input shapes
    # -----------------------------
    class DateRange(TypedDict, total=False):
        start: str
        end: str
 
    class TransactionFilter(TypedDict, total=False):
        # Optional criteria fields used by wrappers
        date_range: DateRange
        category_prefix: str
        merchant: str
        transaction_ids: list[int]
 
    # -----------------------------
    # Tools (decorated wrappers)
    # -----------------------------
    @function_tool
    def run_sql(query: str) -> dict[str, Any]:
        """
        Execute a SQL query against the transaction database and return rows.
        """
        try:
            # Our DB stub requires model and pk_column; use a generic dict model.
            rows: list[dict[str, Any]] = db.run_sql(  # type: ignore[attr-defined]
                query,
                model=dict,  # type: ignore[arg-type]
                pk_column="id",
            )
            # Ensure JSON-serializable
            sanitized = [dict(r) for r in rows]
            return {"rows": sanitized, "row_count": len(sanitized)}
        except Exception as exc:
            return {"error": f"run_sql_failed: {exc!s}"}
 
    @function_tool
    def sync_transactions() -> dict[str, Any]:
        """
        Trigger sync of latest transactions (placeholder).
        """
        # This repository ships with stubs; provide a descriptive response.
        return {
            "status": "not_implemented",
            "message": "Sync is not implemented in this environment.",
        }
 
    @function_tool
    def connect_new_account() -> dict[str, Any]:
        """
        Initiate connecting a new account via Plaid (placeholder).
        """
        return {
            "status": "not_implemented",
            "message": "Account connection flow is not implemented in CLI.",
        }
 
    @function_tool
    def update_category_for_transaction_groups(
        filter: TransactionFilter,  # noqa: A002 - using 'filter' per prompt
        new_category: str,
    ) -> dict[str, Any]:
        """
        Bulk recategorize transactions (placeholder wrapper).
        """
        try:
            # Minimal behavior: if a merchant id was provided via 'merchant',
            # attempt merchant-based recategorization through persist tool stub.
            merchant_str = filter.get("merchant")
            if merchant_str is None:
                return {
                    "updated": 0,
                    "status": "no_op",
                    "message": "Provide 'merchant' in filter for this stub.",
                }
            # Look up merchant id via DB stub (not implemented, placeholder)
            merchant = db.find_merchant_by_normalized_name(  # type: ignore[attr-defined]
                merchant_str
            )
            if merchant is None:
                return {
                    "updated": 0,
                    "status": "no_op",
                    "message": "Merchant not found.",
                }
            # This code path remains a stub since merchant entity is not fleshed out
            updated = persist_tool.bulk_recategorize_by_merchant(
                merchant_id=getattr(merchant, "id", 0),
                category_key=new_category,
                only_unverified=True,
            )
            return {"updated": int(updated)}
        except Exception as exc:
            return {"error": f"recategorize_failed: {exc!s}"}
 
    @function_tool
    def tag_transactions(
        filter: TransactionFilter,  # noqa: A002
        tag: str,
    ) -> dict[str, Any]:
        """
        Apply a tag to transactions matching filter (placeholder).
        """
        try:
            txn_ids = filter.get("transaction_ids") or []
            outcome = persist_tool.apply_tags(txn_ids, [tag])
            return {
                "applied": int(outcome.applied),
                "created_tags": list(outcome.created_tags),
                "transaction_ids": list(txn_ids),
            }
        except Exception as exc:
            return {"error": f"tag_failed: {exc!s}"}
 
    # -----------------------------
    # Build instructions and agent
    # -----------------------------
    template = _load_agent_prompt_template()
    instructions = _render_instructions(
        template,
        db_obj=db,
        taxonomy_obj=taxonomy,
    )
 
    if not _agents_available:
        # Provide a helpful message if user runs this without SDK installed.
        print(
            "The OpenAI Agents SDK is not available. "
            "Install a compatible version of 'openai' providing openai.agents "
            "to use the interactive agent loop.",
            file=sys.stderr,
        )
        return
 
    # Create agent and runner
    agent = Agent(
        name="Transactoid",
        instructions=instructions,
        tools=[
            run_sql,
            sync_transactions,
            connect_new_account,
            update_category_for_transaction_groups,
            tag_transactions,
        ],
    )
    runner = Runner(agent)
 
    # -----------------------------
    # Interactive loop
    # -----------------------------
    print("Transactoid agent ready. Type 'exit' or 'quit' to leave.")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        if not user_input:
            continue
        try:
            # Run a single ReAct iteration synchronously
            result = runner.run_sync(user_input)
            # Assume result has .final_output for the final answer
            final_output = getattr(result, "final_output", None)
            if final_output is None:
                print("(no output)")
            else:
                print(str(final_output))
        except Exception as exc:
            print(f"[error] {exc!s}")


