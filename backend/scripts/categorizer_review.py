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
import json
import os
from typing import Any

from penny.adapters.db.models import DerivedTransaction
from penny.db import get_db


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
        trace_link: str | None = None
        with observability.categorizer_span(
            "categorizer-review",
            input={"transaction_id": txn["transaction_id"], "descriptor": descriptor},
            session_id=f"review-{txn['transaction_id']}",
            metadata={"harness": "categorizer_review"},
        ):
            trace_link = _current_trace_link()
            result = await agent.run(categorizer_agent._build_txn_prompt(txn))
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


async def _main_async(limit: int, out: str) -> None:
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./penny.db")
    print(f"Categorizer review against: {_mask_db_url(db_url)}")
    print("(the agent WRITES categorizations here — use the penny-test branch)\n")

    txns = _select_review_txns(limit)
    if not txns:
        print("No unverified transactions found to review.")
        return
    print(f"Reviewing {len(txns)} transaction(s)...")

    records: list[dict[str, Any]] = []
    for idx, txn in enumerate(txns, start=1):
        print(f"  [{idx}/{len(txns)}] {txn.get('merchant_descriptor')!r} ...")
        records.append(await _review_one(txn))

    with open(out, "w", encoding="utf-8") as handle:
        handle.write(_render_html(records))
    print(f"\nWrote report: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Categorizer review harness")
    parser.add_argument("--limit", type=int, default=10, help="transactions to review")
    parser.add_argument(
        "--out",
        default="/tmp/categorizer_review.html",  # noqa: S108 - one-off local report
        help="output HTML path",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args.limit, args.out))


if __name__ == "__main__":
    main()
