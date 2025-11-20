from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from openai.agents import Agent, Runner, function_tool
from promptorium.services import PromptService
from promptorium.storage.fs import FileSystemPromptStorage
from promptorium.util.repo_root import find_repo_root

from services.db import DB
from services.taxonomy import Taxonomy
from tools.persist.persist_tool import PersistTool

# Module-level context for tool dependencies
_db: DB | None = None
_taxonomy: Taxonomy | None = None
_persist_tool: PersistTool | None = None


def _get_db() -> DB:
    """Get the current DB instance from context."""
    if _db is None:
        raise RuntimeError("DB not initialized. Call run() first.")
    return _db


def _get_taxonomy() -> Taxonomy:
    """Get the current Taxonomy instance from context."""
    if _taxonomy is None:
        raise RuntimeError("Taxonomy not initialized. Call run() first.")
    return _taxonomy


def _get_persist_tool() -> PersistTool:
    """Get the current PersistTool instance from context."""
    if _persist_tool is None:
        raise RuntimeError("PersistTool not initialized. Call run() first.")
    return _persist_tool


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
    filter: dict[str, Any],
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
    taxonomy = _get_taxonomy()
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
    filter: dict[str, Any],
    tag: str,
) -> dict[str, Any]:
    """
    Apply user-defined tags to transactions matching specified criteria.
    
    Args:
        filter: Dictionary with filter criteria
        tag: Tag name to apply
        
    Returns:
        Dictionary with tagging summary
    """
    persist_tool = _get_persist_tool()
    # Note: This is a simplified implementation.
    # The actual implementation should parse the filter and apply tags.
    result = persist_tool.apply_tags([], [tag])
    return {
        "applied": result.applied,
        "created_tags": result.created_tags,
        "status": "not_implemented",
        "message": "Tagging requires filter parsing",
    }


def _load_prompt_template() -> str:
    """Load the agent loop prompt template from Promptorium."""
    repo_root = Path(find_repo_root())
    try:
        storage = FileSystemPromptStorage(repo_root)
        svc = PromptService(storage)
        return str(svc.load_prompt("agent-loop"))
    except Exception:
        # Fallback: read directly from prompts directory
        prompt_path = repo_root / "prompts" / "agent_loop_prompt.md"
        if prompt_path.exists():
            return prompt_path.read_text()
        raise RuntimeError("Could not load agent-loop prompt template")


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
    taxonomy_text = yaml.dump(category_taxonomy, default_flow_style=False, sort_keys=False)
    
    # Replace placeholders
    rendered = template.replace("{{DATABASE_SCHEMA}}", schema_text)
    rendered = rendered.replace("{{CATEGORY_TAXONOMY}}", taxonomy_text)
    
    return rendered


def run(
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
    template = _load_prompt_template()
    schema_hint = db.compact_schema_hint()
    taxonomy_dict = taxonomy.to_prompt()
    instructions = _render_prompt_template(
        template,
        database_schema=schema_hint,
        category_taxonomy=taxonomy_dict,
    )
    
    # Initialize tool dependencies and set module-level context
    global _db, _taxonomy, _persist_tool
    _db = db
    _taxonomy = taxonomy
    _persist_tool = PersistTool(db, taxonomy)
    
    # Create Agent instance
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
    
    # Create Runner instance
    runner = Runner(agent=agent)
    
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
            
            # Run the agent with user input
            result = runner.run_sync(user_input)
            
            # Print agent response
            if result.final_output:
                print(f"\nAgent: {result.final_output}\n")
            else:
                print("\nAgent: (No response generated)\n")
                
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")
            continue


