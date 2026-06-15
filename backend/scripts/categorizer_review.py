"""One-off categorizer review harness (the acceptance gate for the agent).

Pulls N recent UNVERIFIED transactions from the configured DB, runs the new
per-transaction categorizer on each (fast path or agent loop), and writes a
single paged HTML report for human review: chosen category, confidence, the
``categorization_reasoning`` audit text, the tools the agent consulted,
``web_search_summary``, and a best-effort Langfuse trace link.

IMPORTANT: the agent PERSISTS its decisions (writes categories + events). Point
``DATABASE_URL`` at the ``penny-test`` Neon branch (``.env.test``), NEVER prod.

Usage:
    cd backend
    set -a && source .env.test && set +a   # test DB + GOOGLE_API_KEY (+ optional LANGFUSE_*)
    uv run python scripts/categorizer_review.py --limit 10 --out /tmp/categorizer_review.html
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
from typing import Any

from penny.adapters.db.models import DerivedTransaction
from penny.db import get_db


async def _run_agent_traced(
    agent: Any, prompt: str, *, trace_name: str, session_id: str, blind: bool | None
) -> Any:
    """Run the agent with full agent-harness tracing (model turns + tool calls).

    Mirrors production (penny.api.bridge): attach agent-harness's OTEL subscriber
    to an event bus via start_run_trace_task and pass the bus to ``agent.run`` so
    every turn and tool call is exported to Langfuse — not just a single wrapper
    span. No-op tracing when Langfuse is disabled.
    """
    from agent_harness import InMemoryEventBus

    import penny.observability as observability

    tags = ["categorizer-review"]
    if blind is not None:
        tags.append("blind" if blind else "history-on")

    bus = InMemoryEventBus()
    trace_task = observability.start_run_trace_task(
        bus,
        source="categorizer-review",
        trace_name=trace_name,
        session_id=session_id,
        prompt=prompt,
        tags=tags,
    )
    try:
        return await agent.run(prompt=prompt, event_bus=bus)
    finally:
        await bus.close()
        if trace_task is not None:
            with contextlib.suppress(Exception):
                await trace_task


def _normalize_descriptor(descriptor: str) -> str:
    """Collapse a merchant descriptor to its stable core.

    Strips embedded confirmation codes / dates / sequence numbers so that all of a
    merchant's rows (e.g. every "Zelle Payment TO TANIA … #<code>") map to one key.
    Codes are often alphanumeric, so we drop any token containing a digit plus the
    "transaction date …" / "confirmation …" / "#<code>" tails.
    """
    text = descriptor.lower()
    text = re.sub(r"transaction date.*$", "", text)
    text = re.sub(r"confirmation\b.*$", "", text)
    text = re.sub(r"#\S+", "", text)
    # Drop tokens containing a digit (dates, sequence numbers, alnum codes).
    text = " ".join(tok for tok in text.split() if not any(ch.isdigit() for ch in tok))
    # Keep letters/spaces only (drops leftover punctuation like "(xxx)").
    text = re.sub(r"[^a-z ]", " ", text)
    return " ".join(text.split())


def _blind_descriptor_set(reviewed_descriptor: str) -> set[str]:
    """All distinct DB descriptors that normalize to the same merchant.

    Used so descriptor-blinding excludes every sibling row of the merchant under
    review (not just the one row with an identical descriptor).
    """
    from sqlalchemy import text

    if not reviewed_descriptor:
        return set()
    target = _normalize_descriptor(reviewed_descriptor)
    with get_db().session() as session:
        rows = session.execute(
            text(
                "SELECT DISTINCT merchant_descriptor FROM derived_transactions "
                "WHERE merchant_descriptor IS NOT NULL"
            )
        ).fetchall()
    return {r[0] for r in rows if _normalize_descriptor(r[0]) == target}


def _mask_db_url(url: str) -> str:
    """Hide any password in a SQLAlchemy URL for safe printing."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            creds = f"{user}:***"
        return f"{scheme}://{creds}@{host}"
    return url


def _select_review_txns(limit: int) -> list[dict[str, Any]]:
    """Most recent UNVERIFIED transactions (verified rows can't be re-categorized)."""
    db = get_db()
    with db.session() as session:
        rows = (
            session.query(DerivedTransaction)
            .filter(DerivedTransaction.is_verified.is_(False))
            .order_by(DerivedTransaction.posted_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "transaction_id": row.transaction_id,
                "merchant_descriptor": row.merchant_descriptor,
                "amount": row.amount_cents / 100.0,
                "date": row.posted_at.isoformat() if row.posted_at else None,
            }
            for row in rows
        ]


def _current_trace_link() -> str | None:
    """Best-effort Langfuse trace URL for the active OTEL span (None if untraced)."""
    try:
        from opentelemetry import trace as otel_trace

        ctx = otel_trace.get_current_span().get_span_context()
        if not ctx or not ctx.trace_id:
            return None
        trace_id = format(ctx.trace_id, "032x")
    except Exception:
        return None
    host = (
        os.environ.get("LANGFUSE_HOST")
        or os.environ.get("LANGFUSE_BASE_URL")
        or "https://us.cloud.langfuse.com"
    ).rstrip("/")
    # Langfuse URL shape varies by version/project; this is a best-effort deep link.
    return f"{host}/trace/{trace_id}"


def _extract_from_result(result: Any) -> tuple[list[str], dict[str, Any]]:
    """Pull the tool-call names and submit_categorization args from a RunResult."""
    tools_called: list[str] = []
    submit_args: dict[str, Any] = {}
    for message in getattr(result, "messages", []) or []:
        for block in getattr(message, "content", []) or []:
            if getattr(block, "type", None) == "tool_call":
                name = getattr(block, "name", "")
                tools_called.append(name)
                if name == "submit_categorization":
                    submit_args = dict(getattr(block, "arguments", {}) or {})
    return tools_called, submit_args


async def _review_one(txn: dict[str, Any]) -> dict[str, Any]:
    """Run the categorizer on one txn and collect everything needed for the report."""
    # Imported lazily so the module loads even when agent deps aren't configured.
    from penny.tools._services import categorizer_agent
    from penny.tools._services.categorizer_agent import build_categorizer_agent

    db = get_db()
    descriptor = txn.get("merchant_descriptor") or ""
    record: dict[str, Any] = {
        "transaction_id": txn["transaction_id"],
        "merchant_descriptor": descriptor,
        "amount": txn.get("amount"),
        "date": txn.get("date"),
    }

    verified_key = (
        db.verified_category_for_descriptor(descriptor) if descriptor else None
    )
    if verified_key:
        categorizer_agent._apply_fast_path(db, txn["transaction_id"], verified_key)
        record.update(
            method="fast_path",
            category_key=verified_key,
            confidence=1.0,
            reasoning="Exact verified match for this merchant descriptor (no LLM).",
            tools_consulted=[],
            trace_link=None,
        )
    else:
        import penny.observability as observability

        agent = build_categorizer_agent()
        tid = txn["transaction_id"]
        trace_link: str | None = None
        with observability.categorizer_span(
            "categorizer-review",
            input={"transaction_id": tid, "descriptor": descriptor},
            session_id=f"review-{tid}",
            metadata={"harness": "categorizer_review"},
        ):
            trace_link = _current_trace_link()
            result = await _run_agent_traced(
                agent,
                categorizer_agent._build_txn_prompt(txn),
                trace_name="categorizer-review",
                session_id=f"review-{tid}",
                blind=None,
            )
        tools_called, submit_args = _extract_from_result(result)
        record.update(
            method="agent",
            category_key=submit_args.get("category_key"),
            confidence=submit_args.get("confidence"),
            reasoning=submit_args.get("reasoning"),
            evidence=submit_args.get("evidence"),
            tools_consulted=tools_called,
            trace_link=trace_link,
        )

    # Read back persisted audit + web_search_summary from the DB.
    events = db.events_for_transaction(txn["transaction_id"])
    if events:
        record.setdefault("category_key", events[-1].get("to_category_key"))
        record["categorization_reasoning"] = events[-1].get("categorization_reasoning")
    with db.session() as session:
        row = (
            session.query(DerivedTransaction)
            .filter(DerivedTransaction.transaction_id == txn["transaction_id"])
            .one_or_none()
        )
        record["web_search_summary"] = row.web_search_summary if row else None
    return record


def _count_turns(result: Any) -> int:
    """Number of model turns = assistant messages in the run."""
    return sum(
        1
        for m in getattr(result, "messages", []) or []
        if getattr(m, "role", None) == "assistant"
    )


def _select_recategorized_txns(limit: int) -> list[dict[str, Any]]:
    """Transactions the user manually recategorized (a real category change).

    Deduped by merchant descriptor for variety. Each carries its prior-recat
    context (from -> to + reason) so the report can show whether the agent now
    reproduces the user's correction.
    """
    from sqlalchemy import text

    db = get_db()
    with db.session() as session:
        rows = session.execute(
            text(
                """
                SELECT e.transaction_id, e.from_category_key, e.to_category_key,
                       e.recategorization_reason,
                       d.merchant_descriptor, d.merchant_id, d.amount_cents,
                       d.posted_at, c.key AS current_category
                FROM transaction_category_events e
                JOIN derived_transactions d ON d.transaction_id = e.transaction_id
                LEFT JOIN categories c ON c.category_id = d.category_id
                WHERE e.method = 'manual'
                  AND e.from_category_key IS NOT NULL
                  AND e.from_category_key <> e.to_category_key
                ORDER BY e.created_at DESC
                """
            )
        ).fetchall()

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        descriptor = row.merchant_descriptor or ""
        key = _normalize_descriptor(descriptor) or descriptor
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "transaction_id": row.transaction_id,
                "merchant_descriptor": descriptor,
                "merchant_id": row.merchant_id,
                "amount": row.amount_cents / 100.0,
                "date": row.posted_at.isoformat() if row.posted_at else None,
                "recat_from": row.from_category_key,
                "recat_to": row.to_category_key,
                "recat_reason": row.recategorization_reason,
                "current_category": row.current_category,
            }
        )
        if len(out) >= limit:
            break
    return out


async def _review_one_recategorized(
    item: dict[str, Any], *, blind: bool = False
) -> dict[str, Any]:
    """Dry-run the agent on a previously-recategorized txn (no persistence).

    ``blind=True`` hides this merchant's own rows/events from the read API (the
    agent keeps all its tools, but lookups for *this* merchant return nothing), so
    it can't read back the prior (corrected) categorization of the row under test.
    """
    from penny.adapters.db.facade import review_blind_exclusions
    import penny.observability as observability
    from penny.tools._services import categorizer_agent
    from penny.tools._services.categorizer_agent import build_categorizer_agent

    # Blind by normalized merchant_descriptor: hide ALL of this merchant's rows
    # (every descriptor that normalizes the same), not just the one identical row,
    # so confirmation-code/date variants (Zelle, ATM, …) can't leak the answer.
    descriptors = (
        _blind_descriptor_set(item.get("merchant_descriptor") or "") if blind else set()
    )

    tid = item["transaction_id"]
    prompt = categorizer_agent._build_txn_prompt(item)
    trace_link: str | None = None
    with review_blind_exclusions(descriptors=descriptors):
        # Build inside the exclusion context so the prompt's recent-events block
        # is blinded too.
        agent = build_categorizer_agent()
        # Thin outer span owns the trace id (for the report link); the harness
        # subscriber attached in _run_agent_traced nests its model-turn / tool-call
        # spans under it, so the trace shows the full agent loop, not one span.
        with observability.categorizer_span(
            "categorizer-review-recat",
            input={"transaction_id": tid},
            session_id=f"review-recat-{tid}",
            metadata={"harness": "categorizer_review", "blind": blind},
        ):
            trace_link = _current_trace_link()
            result = await _run_agent_traced(
                agent,
                prompt,
                trace_name="categorizer-review-recat",
                session_id=f"review-recat-{tid}",
                blind=blind,
            )
    tools_called, submit_args = _extract_from_result(result)
    agent_category = submit_args.get("category_key")
    return {
        **item,
        # Plaid's own category is not persisted in this schema (dropped at ingest).
        "plaid_category": None,
        "blind": blind,
        "agent_category": agent_category,
        "confidence": submit_args.get("confidence"),
        "reasoning": submit_args.get("reasoning"),
        "evidence": submit_args.get("evidence"),
        "tools_consulted": tools_called,
        "turns": _count_turns(result),
        "trace_link": trace_link,
        "agrees_with_recat": agent_category == item.get("recat_to"),
    }


def _render_recat_html(records: list[dict[str, Any]]) -> str:
    """Paged HTML report for the recategorized-transactions review."""
    payload = json.dumps(records)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Categorizer review — recategorized</title>
<style>
  body {{ font: 15px/1.55 -apple-system, system-ui, sans-serif; max-width: 860px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  .nav {{ display:flex; gap:.75rem; align-items:center; margin-bottom:1rem; }}
  button {{ font: inherit; padding:.35rem .8rem; cursor:pointer; }}
  .card {{ border:1px solid #ddd; border-radius:10px; padding:1.25rem 1.5rem; }}
  .desc {{ font-size:1.3rem; font-weight:600; }}
  .meta {{ color:#666; margin:.25rem 0 1rem; }}
  .row {{ margin:.5rem 0; }} .k {{ color:#666; }}
  .agree {{ font-weight:600; }} .ok {{ color:#0a7; }} .no {{ color:#c33; }}
  .turns {{ font-weight:600; }}
  pre {{ white-space:pre-wrap; background:#fafafa; border:1px solid #eee;
        border-radius:8px; padding:.75rem; }}
  .tools span {{ display:inline-block; background:#f0f0f0; border-radius:6px;
        padding:.1rem .5rem; margin:.15rem; font-size:.85rem; }}
  .flow {{ font-family: ui-monospace, monospace; background:#f6f6ff; padding:.5rem .75rem;
        border-radius:8px; }}
  a {{ color:#06c; }}
</style></head><body>
<h1>Categorizer review — previously recategorized</h1>
<p class="meta">Dry run (no writes). Does the agent now reproduce the user's past correction?</p>
<div class="nav">
  <button id="prev">&larr; Prev</button>
  <span id="counter"></span>
  <button id="next">Next &rarr;</button>
</div>
<div id="card" class="card"></div>
<script>
const R = {payload};
let i = 0;
function esc(s) {{ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function render() {{
  const r = R[i];
  document.getElementById('counter').textContent = `${{i+1}} / ${{R.length}}`;
  const tools = (r.tools_consulted||[]).filter(t=>t!=='submit_categorization').map(t => `<span>${{esc(t)}}</span>`).join('') || '<span>(none)</span>';
  const conf = r.confidence==null ? '—' : Number(r.confidence).toFixed(2);
  const agree = r.agrees_with_recat ? '<span class="agree ok">agrees with user correction</span>' : '<span class="agree no">differs from user correction</span>';
  const trace = r.trace_link ? `<a href="${{esc(r.trace_link)}}" target="_blank">Langfuse trace</a>` : '<span class="k">no trace</span>';
  document.getElementById('card').innerHTML = `
    <div class="desc">${{esc(r.merchant_descriptor)||'(no descriptor)'}}</div>
    <div class="meta">txn #${{r.transaction_id}} &middot; $${{esc(r.amount)}} &middot; ${{esc(r.date)}}</div>
    <div class="row"><span class="k">Plaid category:</span> ${{r.plaid_category==null ? '<i>not stored (dropped at ingest)</i>' : esc(r.plaid_category)}}</div>
    <div class="row"><span class="k">User correction:</span>
      <span class="flow">${{esc(r.recat_from)}} &rarr; ${{esc(r.recat_to)}}</span>
      <span class="k">(${{esc(r.recat_reason)||'no reason'}})</span></div>
    <div class="row"><span class="k">Current category:</span> ${{esc(r.current_category)}}</div>
    <hr>
    <div class="row"><span class="k">Agent now picks:</span> <b>${{esc(r.agent_category)}}</b>
      &nbsp; conf=${{conf}} &nbsp; ${{agree}}</div>
    <div class="row"><span class="k">Turns:</span> <span class="turns">${{r.turns}}</span></div>
    <div class="row"><span class="k">Reasoning:</span><pre>${{esc(r.reasoning)}}</pre></div>
    <div class="row tools"><span class="k">Tools consulted:</span> ${{tools}}</div>
    <div class="row">${{trace}}</div>`;
}}
document.getElementById('prev').onclick = () => {{ if (i>0) {{ i--; render(); }} }};
document.getElementById('next').onclick = () => {{ if (i<R.length-1) {{ i++; render(); }} }};
document.addEventListener('keydown', e => {{ if (e.key==='ArrowLeft') document.getElementById('prev').click(); if (e.key==='ArrowRight') document.getElementById('next').click(); }});
render();
</script></body></html>
"""


def _render_html(records: list[dict[str, Any]]) -> str:
    """Single-file, paged HTML report (one transaction per page)."""
    payload = json.dumps(records)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Categorizer review</title>
<style>
  body {{ font: 15px/1.55 -apple-system, system-ui, sans-serif; max-width: 820px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  .nav {{ display:flex; gap:.75rem; align-items:center; margin-bottom:1rem; }}
  button {{ font: inherit; padding:.35rem .8rem; cursor:pointer; }}
  .card {{ border:1px solid #ddd; border-radius:10px; padding:1.25rem 1.5rem; }}
  .desc {{ font-size:1.3rem; font-weight:600; }}
  .meta {{ color:#666; margin:.25rem 0 1rem; }}
  .row {{ margin:.5rem 0; }} .k {{ color:#666; }}
  .cat {{ font-weight:600; }} .conf {{ color:#0a7; }}
  .badge {{ font-size:.75rem; padding:.1rem .5rem; border-radius:6px; background:#eef; }}
  .badge.agent {{ background:#fee9d6; }}
  pre {{ white-space:pre-wrap; background:#fafafa; border:1px solid #eee;
        border-radius:8px; padding:.75rem; }}
  .tools span {{ display:inline-block; background:#f0f0f0; border-radius:6px;
        padding:.1rem .5rem; margin:.15rem; font-size:.85rem; }}
  a {{ color:#06c; }}
</style></head><body>
<h1>Categorizer review</h1>
<div class="nav">
  <button id="prev">&larr; Prev</button>
  <span id="counter"></span>
  <button id="next">Next &rarr;</button>
</div>
<div id="card" class="card"></div>
<script>
const R = {payload};
let i = 0;
function esc(s) {{ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function render() {{
  const r = R[i];
  document.getElementById('counter').textContent = `${{i+1}} / ${{R.length}}`;
  const tools = (r.tools_consulted||[]).map(t => `<span>${{esc(t)}}</span>`).join('') || '<span>(none)</span>';
  const conf = r.confidence==null ? '—' : Number(r.confidence).toFixed(2);
  const trace = r.trace_link ? `<a href="${{esc(r.trace_link)}}" target="_blank">Langfuse trace</a>` : '<span class="k">no trace</span>';
  document.getElementById('card').innerHTML = `
    <div class="desc">${{esc(r.merchant_descriptor)||'(no descriptor)'}}
      <span class="badge ${{r.method}}">${{esc(r.method)}}</span></div>
    <div class="meta">txn #${{r.transaction_id}} &middot; $${{esc(r.amount)}} &middot; ${{esc(r.date)}}</div>
    <div class="row"><span class="k">Category:</span> <span class="cat">${{esc(r.category_key)}}</span>
      &nbsp; <span class="k">Confidence:</span> <span class="conf">${{conf}}</span></div>
    <div class="row"><span class="k">Reasoning (audit):</span><pre>${{esc(r.categorization_reasoning || r.reasoning)}}</pre></div>
    <div class="row"><span class="k">Web search summary:</span><pre>${{esc(r.web_search_summary)||'(none)'}}</pre></div>
    <div class="row tools"><span class="k">Tools consulted:</span> ${{tools}}</div>
    <div class="row">${{trace}}</div>`;
}}
document.getElementById('prev').onclick = () => {{ if (i>0) {{ i--; render(); }} }};
document.getElementById('next').onclick = () => {{ if (i<R.length-1) {{ i++; render(); }} }};
document.addEventListener('keydown', e => {{ if (e.key==='ArrowLeft') document.getElementById('prev').click(); if (e.key==='ArrowRight') document.getElementById('next').click(); }});
render();
</script></body></html>
"""


async def _main_async(mode: str, limit: int, out: str, *, blind: bool = False) -> None:
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./penny.db")
    print(f"Categorizer review ({mode}) against: {_mask_db_url(db_url)}")

    if mode == "recategorized":
        # Dry run: review the agent's decision without persisting anything.
        os.environ["PENNY_CATEGORIZER_DRY_RUN"] = "1"
        print(f"(dry run — no writes; blind={blind})\n")
        items = _select_recategorized_txns(limit)
        if not items:
            print("No recategorized transactions found.")
            return
        print(f"Reviewing {len(items)} recategorized transaction(s)...")
        records: list[dict[str, Any]] = []
        for idx, item in enumerate(items, start=1):
            print(f"  [{idx}/{len(items)}] {item.get('merchant_descriptor')!r} ...")
            records.append(await _review_one_recategorized(item, blind=blind))
        html_doc = _render_recat_html(records)
    else:
        print("(the agent WRITES categorizations here — use the penny-test branch)\n")
        txns = _select_review_txns(limit)
        if not txns:
            print("No unverified transactions found to review.")
            return
        print(f"Reviewing {len(txns)} transaction(s)...")
        records = []
        for idx, txn in enumerate(txns, start=1):
            print(f"  [{idx}/{len(txns)}] {txn.get('merchant_descriptor')!r} ...")
            records.append(await _review_one(txn))
        html_doc = _render_html(records)

    with open(out, "w", encoding="utf-8") as handle:
        handle.write(html_doc)
    print(f"\nWrote report: {out}")

    # Force-flush spans so the full per-turn traces export before the script exits.
    import penny.observability as observability

    observability.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Categorizer review harness")
    parser.add_argument(
        "--mode",
        choices=["recent", "recategorized"],
        default="recent",
        help="recent unverified txns (writes) or previously-recategorized txns (dry run)",
    )
    parser.add_argument("--limit", type=int, default=10, help="transactions to review")
    parser.add_argument(
        "--blind",
        action="store_true",
        help="recategorized mode only: withhold history/tags tools + recent events "
        "so the agent can't reference the merchant's prior categorization",
    )
    parser.add_argument(
        "--out",
        default="/tmp/categorizer_review.html",  # noqa: S108 - one-off local report
        help="output HTML path",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args.mode, args.limit, args.out, blind=args.blind))


if __name__ == "__main__":
    main()
