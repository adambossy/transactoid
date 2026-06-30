"""Render the legacy-vs-agent review report (emailed on disagreement runs).

Pure rendering over the in-memory item dicts the job produced this run (richer
than the persisted ``eval_items`` row — includes amount/date/tools). Only runs
with at least one legacy!=agent disagreement are emailed.
"""

from __future__ import annotations

import html
import json
from typing import Any


def disagreements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items where the agent's pick differs from the legacy baseline."""
    return [it for it in items if it.get("legacy_key") != it.get("agent_key")]


def render_eval_report(
    items: list[dict[str, Any]], *, run_at: str, version: dict[str, Any]
) -> str:
    """Single-file paged HTML report (one transaction per page)."""
    payload = json.dumps(items)
    n_disagree = len(disagreements(items))
    stamp = html.escape(
        " · ".join(f"{k}={v}" for k, v in version.items() if v) or "(no version stamp)"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Categorizer eval — {html.escape(run_at)}</title>
<style>
  body {{ font: 15px/1.55 -apple-system, system-ui, sans-serif; max-width: 820px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  .nav {{ display:flex; gap:.75rem; align-items:center; margin-bottom:1rem; }}
  button {{ font: inherit; padding:.35rem .8rem; cursor:pointer; }}
  .card {{ border:1px solid #ddd; border-radius:10px; padding:1.25rem 1.5rem; }}
  .desc {{ font-size:1.3rem; font-weight:600; }}
  .meta {{ color:#666; margin:.25rem 0 1rem; }}
  .row {{ margin:.5rem 0; }} .k {{ color:#666; }}
  .flow {{ font-family: ui-monospace, monospace; background:#f6f6ff; padding:.4rem .7rem;
        border-radius:8px; }}
  .agree {{ color:#0a7; font-weight:600; }} .differ {{ color:#c33; font-weight:600; }}
  pre {{ white-space:pre-wrap; background:#fafafa; border:1px solid #eee;
        border-radius:8px; padding:.75rem; }}
  .tools span {{ display:inline-block; background:#f0f0f0; border-radius:6px;
        padding:.1rem .5rem; margin:.15rem; font-size:.85rem; }}
  a {{ color:#06c; }}
</style></head><body>
<h1>Categorizer eval — {html.escape(run_at)}</h1>
<p class="meta">{len(items)} transaction(s), {n_disagree} disagreement(s) ·
  version: {stamp}</p>
<div class="nav">
  <button id="prev">&larr; Prev</button><span id="counter"></span>
  <button id="next">Next &rarr;</button>
  <label><input type="checkbox" id="only"> disagreements only</label>
</div>
<div id="card" class="card"></div>
<script>
const ALL = {payload};
let R = ALL, i = 0;
function esc(s) {{ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function render() {{
  if (R.length === 0) {{ document.getElementById('card').innerHTML = '(nothing)'; document.getElementById('counter').textContent=''; return; }}
  if (i >= R.length) i = R.length - 1;
  const r = R[i];
  document.getElementById('counter').textContent = `${{i+1}} / ${{R.length}}`;
  const tools = (r.tools_consulted||[]).filter(t=>t!=='submit_categorization').map(t => `<span>${{esc(t)}}</span>`).join('') || '<span>(none)</span>';
  const conf = r.agent_confidence==null ? '—' : Number(r.agent_confidence).toFixed(2);
  const differ = r.legacy_key !== r.agent_key;
  const verdict = differ ? '<span class="differ">legacy ≠ agent</span>' : '<span class="agree">agree</span>';
  const trace = r.trace_link ? `<a href="${{esc(r.trace_link)}}" target="_blank">Langfuse trace</a>` : '<span class="k">no trace</span>';
  document.getElementById('card').innerHTML = `
    <div class="desc">${{esc(r.merchant_descriptor)||'(no descriptor)'}}</div>
    <div class="meta">txn #${{r.transaction_id}} &middot; $${{esc(r.amount)}} &middot; ${{esc(r.date)}} &middot; ${{esc(r.method)}}</div>
    <div class="row"><span class="flow">${{esc(r.legacy_key)}} &rarr; ${{esc(r.agent_key)}}</span> &nbsp; ${{verdict}} &nbsp; <span class="k">conf</span> ${{conf}}</div>
    <div class="row"><span class="k">Agent reasoning:</span><pre>${{esc(r.agent_reasoning)}}</pre></div>
    <div class="row tools"><span class="k">Tools:</span> ${{tools}}</div>
    <div class="row">${{trace}}</div>`;
}}
document.getElementById('prev').onclick = () => {{ if (i>0) {{ i--; render(); }} }};
document.getElementById('next').onclick = () => {{ if (i<R.length-1) {{ i++; render(); }} }};
document.getElementById('only').onchange = (e) => {{ R = e.target.checked ? ALL.filter(x=>x.legacy_key!==x.agent_key) : ALL; i=0; render(); }};
document.addEventListener('keydown', e => {{ if (e.key==='ArrowLeft') document.getElementById('prev').click(); if (e.key==='ArrowRight') document.getElementById('next').click(); }});
render();
</script></body></html>
"""
