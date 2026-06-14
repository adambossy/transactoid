"""Per-transaction categorizer agent (agent-harness based).

This is the new categorization path: instead of a single-shot batch LLM call, each
transaction is decided by a short-lived, ephemeral agent that can consult history,
tags, the events log, and web_search before committing a decision via the final
``submit_categorization`` tool.

Two tiers:
- **Fast path (no LLM)** — an exact merchant descriptor that already has a VERIFIED
  categorization is reused at confidence 1.0 and the new row is marked verified.
- **Agent path** — everything else runs the agent loop.

The agent is built WITHOUT filesystem/bash/skills tools (capability confinement) and
runs in-process with its own per-run scratch sandbox under ``~/.transactoid``.
"""

from __future__ import annotations

from datetime import date
from typing import Any
import uuid

from agent_harness import Agent
from agent_harness.core.models import ModelSettings
from agent_harness.sandboxes.inprocess import InProcessSandbox
import yaml

from penny.agent_factory import build_model
from penny.db import get_db
from penny.prompts import load_prompt
from penny.services import get_rules_loader, get_taxonomy
from penny.taxonomy.loader import get_category_id
from penny.tools._services.categorizer_tools import build_categorizer_toolset
from penny.workspace import resolve_workspace_dir

# Provider-native web_search. Adding this to the model's wire ``tools`` list lets
# the agent search the web for unknown merchants. NOTE: agent-harness providers
# currently OVERWRITE ``config["tools"]`` from ``ModelSettings.extra``
# (providers/google.py:312-321, providers/openai.py:256-264), which would drop the
# function tools (incl. submit_categorization). Enabling web_search therefore needs
# the provider to APPEND builtin tools rather than overwrite. Flip ``_ENABLE_WEB_SEARCH``
# on once that hook lands; the tool spec itself is the single dict below.
_GEMINI_WEB_SEARCH_TOOL: dict[str, Any] = {"google_search": {}}
_ENABLE_WEB_SEARCH = False


def _format_recent_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    lines = []
    for event in events:
        when = (event.get("created_at") or "")[:10]
        descriptor = event.get("merchant_descriptor") or "?"
        frm = event.get("from_category_key") or "—"
        to = event.get("to_category_key") or "?"
        why = (
            event.get("recategorization_reason")
            or event.get("categorization_reasoning")
            or ""
        )
        why = why.replace("\n", " ")[:120]
        lines.append(
            f"- [{when}] {descriptor}: {frm} → {to} ({event.get('method')}) {why}"
        )
    return "\n".join(lines)


def _render_categorizer_prompt() -> str:
    """Render the categorizer agent's system prompt with live context."""
    taxonomy = get_taxonomy()
    template = load_prompt("categorize-transaction-agent")
    taxonomy_text = yaml.dump(
        taxonomy.to_prompt(), default_flow_style=False, sort_keys=False
    )
    try:
        taxonomy_rules = load_prompt("taxonomy-rules")
    except Exception:
        taxonomy_rules = ""
    rules_loader = get_rules_loader()
    merchant_rules = (
        rules_loader.load() if rules_loader else ""
    ) or "(no merchant rules)"
    recent_events = _format_recent_events(get_db().recent_category_events(limit=15))

    rendered = template.replace("{{CURRENT_DATE}}", date.today().isoformat())
    rendered = rendered.replace("{{TAXONOMY_HIERARCHY}}", taxonomy_text)
    rendered = rendered.replace("{{TAXONOMY_RULES}}", taxonomy_rules)
    rendered = rendered.replace("{{MERCHANT_RULES}}", merchant_rules)
    rendered = rendered.replace("{{RECENT_EVENTS}}", recent_events or "(none yet)")
    return rendered


def build_categorizer_agent() -> Agent:
    """Build a fresh, ephemeral categorizer agent with its own scratch sandbox."""
    run_id = uuid.uuid4().hex
    scratch_root = resolve_workspace_dir() / "agent-runs" / run_id
    sandbox = InProcessSandbox(root=str(scratch_root))

    extra: dict[str, Any] = {}
    if _ENABLE_WEB_SEARCH:
        extra["tools"] = [_GEMINI_WEB_SEARCH_TOOL]

    return Agent(
        name="categorizer",
        model=build_model(),  # gemini-3.5-flash
        instructions=_render_categorizer_prompt(),
        session=None,
        persist_session=False,
        sandbox=sandbox,
        model_settings=ModelSettings(thinking_budget=-1, extra=extra),
        toolsets=[build_categorizer_toolset()],
    )


def _build_txn_prompt(txn: dict[str, Any]) -> str:
    amount = txn.get("amount")
    amount_str = f"${amount:.2f}" if isinstance(amount, (int, float)) else "unknown"
    return (
        "Categorize this single transaction. Pass the exact transaction_id below to "
        "submit_categorization when you are done.\n\n"
        f"- transaction_id: {txn['transaction_id']}\n"
        f"- merchant descriptor: {txn.get('merchant_descriptor') or '(none)'}\n"
        f"- amount: {amount_str}\n"
        f"- date: {txn.get('date') or 'unknown'}\n"
    )


def _apply_fast_path(db: Any, transaction_id: int, category_key: str) -> None:
    """Reuse a verified category for an exact descriptor; mark the row verified."""
    category_id = get_category_id(db, get_taxonomy(), category_key)
    if category_id is None:
        raise ValueError(f"Category ID not found for key: {category_key!r}")
    db.update_derived_mutable(
        transaction_id,
        {
            "category_id": category_id,
            "category_method": "manual",
            "category_reason": (
                "Fast path: reused an existing verified categorization for this "
                "exact merchant descriptor."
            ),
            "is_verified": True,
        },
    )


def _read_decision(db: Any, transaction_id: int) -> dict[str, Any] | None:
    events = db.events_for_transaction(transaction_id)
    if not events:
        return None
    latest = events[-1]
    return {
        "transaction_id": transaction_id,
        "category_key": latest.get("to_category_key"),
        "reasoning": latest.get("categorization_reasoning"),
        "method": latest.get("method"),
    }


async def categorize_one(txn: dict[str, Any]) -> dict[str, Any]:
    """Categorize one derived transaction.

    Args:
        txn: dict with at least ``transaction_id`` and ``merchant_descriptor``
            (``amount`` / ``date`` are used to enrich the agent prompt).

    Returns:
        A decision dict ``{transaction_id, category_key, confidence?, method, reasoning}``.
        ``method`` is ``"fast_path"`` when the verified-match shortcut fired, else the
        agent's decision (read back from the persisted event).
    """
    db = get_db()
    transaction_id = txn["transaction_id"]
    descriptor = txn.get("merchant_descriptor") or ""

    if descriptor:
        verified_key = db.verified_category_for_descriptor(descriptor)
        if verified_key:
            _apply_fast_path(db, transaction_id, verified_key)
            return {
                "transaction_id": transaction_id,
                "category_key": verified_key,
                "confidence": 1.0,
                "method": "fast_path",
                "reasoning": (f"Exact verified match for descriptor {descriptor!r}."),
            }

    agent = build_categorizer_agent()
    await agent.run(_build_txn_prompt(txn))
    # submit_categorization persisted the decision; read it back for the caller.
    decision = _read_decision(db, transaction_id)
    if decision is None:
        return {
            "transaction_id": transaction_id,
            "category_key": None,
            "method": "agent",
            "reasoning": "Agent did not submit a categorization.",
        }
    return decision
