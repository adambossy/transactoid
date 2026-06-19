"""Build the human-in-the-loop validation page for normalizer dry-runs.

The page replaces the (dropped) automated backfill: it walks the reviewer
through each proposed merchant identity and the descriptors that would collapse
into it, with a per-proposal correct/incorrect checkbox and notes field. It is
the acceptance gate for the extraction-rule repository, not a migration tool.

``build_review_html`` is a pure function (no I/O, no LLM) so it can be unit
tested; the dry-run script feeds it proposals computed by the normalizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html
import json


@dataclass(frozen=True, slots=True)
class ProposalMember:
    """One raw descriptor that maps into a proposed identity."""

    descriptor: str
    count: int


@dataclass(frozen=True, slots=True)
class ReviewProposal:
    """A proposed normalized identity and the descriptors collapsing into it."""

    normalized_name: str
    display_name: str
    source_channel: str
    counterparty: str | None
    members: list[ProposalMember] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return sum(m.count for m in self.members)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def build_review_html(proposals: list[ReviewProposal], *, title: str) -> str:
    """Render proposals into a self-contained validation HTML page.

    Proposals are sorted so the highest-impact merges (most descriptors, then
    most transactions) come first. Each card carries a correct/incorrect
    checkbox and a notes box; state persists in localStorage keyed by
    normalized_name so a reviewer can stop and resume.
    """
    ordered = sorted(
        proposals,
        key=lambda p: (len(p.members), p.total_count),
        reverse=True,
    )
    multi = [p for p in ordered if len(p.members) > 1]

    cards: list[str] = []
    for p in ordered:
        members_rows = "\n".join(
            f'<tr><td class="cnt">{m.count}×</td>'
            f"<td><code>{_esc(m.descriptor)}</code></td></tr>"
            for m in sorted(p.members, key=lambda m: -m.count)
        )
        cp = _esc(p.counterparty) if p.counterparty else "<em>—</em>"
        merge_badge = (
            f'<span class="badge merge">{len(p.members)} descriptors → 1</span>'
            if len(p.members) > 1
            else '<span class="badge">single</span>'
        )
        cards.append(
            f"""
        <section class="card" data-key="{_esc(p.normalized_name)}">
          <header>
            <div class="ids">
              <code class="nm">{_esc(p.normalized_name)}</code>
              <span class="chan">{_esc(p.source_channel)}</span>
              {merge_badge}
            </div>
            <div class="meta">display: <strong>{_esc(p.display_name)}</strong>
              &nbsp;·&nbsp; counterparty: {cp}
              &nbsp;·&nbsp; {p.total_count} txns</div>
          </header>
          <table class="members"><tbody>{members_rows}</tbody></table>
          <footer>
            <label class="ok"><input type="checkbox" class="correct"> correct</label>
            <label class="bad"><input type="checkbox" class="incorrect"> incorrect</label>
            <input type="text" class="note" placeholder="notes…">
          </footer>
        </section>"""
        )

    summary = {
        "total": len(ordered),
        "merges": len(multi),
        "channels": sorted({p.source_channel for p in ordered}),
    }

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #f6f7f9; color: #16181d; }}
  header.top {{ position: sticky; top: 0; background: #fff; border-bottom: 1px solid #e3e6ea;
    padding: 14px 20px; display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }}
  header.top h1 {{ font-size: 18px; margin: 0; }}
  .counts {{ color: #5b616e; font-size: 13px; }}
  #progress {{ font-weight: 600; }}
  main {{ max-width: 920px; margin: 0 auto; padding: 18px; }}
  .card {{ background: #fff; border: 1px solid #e3e6ea; border-radius: 10px;
    margin: 0 0 14px; padding: 14px 16px; }}
  .card.done-ok {{ border-color: #34a853; box-shadow: inset 3px 0 #34a853; }}
  .card.done-bad {{ border-color: #ea4335; box-shadow: inset 3px 0 #ea4335; }}
  .ids {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  code.nm {{ font-size: 14px; background: #eef1f5; padding: 2px 7px; border-radius: 6px; }}
  .chan {{ font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    color: #fff; background: #5b6470; padding: 2px 7px; border-radius: 20px; }}
  .badge {{ font-size: 11px; color: #5b616e; }}
  .badge.merge {{ color: #1a73e8; font-weight: 600; }}
  .meta {{ color: #5b616e; font-size: 13px; margin-top: 6px; }}
  table.members {{ width: 100%; border-collapse: collapse; margin: 10px 0 4px;
    display: block; overflow-x: auto; }}
  table.members td {{ padding: 3px 6px; vertical-align: top; border-top: 1px solid #f0f2f4; }}
  td.cnt {{ color: #8a909c; white-space: nowrap; text-align: right; width: 48px; }}
  code {{ font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; }}
  footer {{ display: flex; gap: 16px; align-items: center; margin-top: 8px; flex-wrap: wrap; }}
  footer label {{ font-size: 13px; cursor: pointer; user-select: none; }}
  footer .note {{ flex: 1; min-width: 160px; padding: 5px 8px; border: 1px solid #d6dae0;
    border-radius: 6px; font: inherit; }}
</style></head>
<body>
<header class="top">
  <h1>{_esc(title)}</h1>
  <span class="counts">{summary["total"]} identities · {summary["merges"]} merges ·
    channels: {_esc(", ".join(summary["channels"]))}</span>
  <span id="progress"></span>
  <button id="export">Export results</button>
</header>
<main>{"".join(cards)}</main>
<script>
const KEY = "normalizer-review";
const state = JSON.parse(localStorage.getItem(KEY) || "{{}}");
function persist() {{ localStorage.setItem(KEY, JSON.stringify(state)); render(); }}
function render() {{
  let done = 0;
  document.querySelectorAll(".card").forEach(card => {{
    const k = card.dataset.key, s = state[k] || {{}};
    card.querySelector(".correct").checked = !!s.correct;
    card.querySelector(".incorrect").checked = !!s.incorrect;
    card.querySelector(".note").value = s.note || "";
    card.classList.toggle("done-ok", !!s.correct);
    card.classList.toggle("done-bad", !!s.incorrect);
    if (s.correct || s.incorrect) done++;
  }});
  const total = document.querySelectorAll(".card").length;
  document.getElementById("progress").textContent = `reviewed ${{done}}/${{total}}`;
}}
document.querySelectorAll(".card").forEach(card => {{
  const k = card.dataset.key;
  const get = () => state[k] || (state[k] = {{}});
  card.querySelector(".correct").addEventListener("change", e => {{
    const s = get(); s.correct = e.target.checked; if (s.correct) s.incorrect = false; persist();
  }});
  card.querySelector(".incorrect").addEventListener("change", e => {{
    const s = get(); s.incorrect = e.target.checked; if (s.incorrect) s.correct = false; persist();
  }});
  card.querySelector(".note").addEventListener("input", e => {{ get().note = e.target.value; persist(); }});
}});
document.getElementById("export").addEventListener("click", () => {{
  const blob = new Blob([JSON.stringify(state, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "normalizer-review-results.json"; a.click();
}});
render();
</script>
</body></html>"""


def proposals_to_json(proposals: list[ReviewProposal]) -> str:
    """Serialize proposals (for re-running / diffing outside the browser)."""
    return json.dumps(
        [
            {
                "normalized_name": p.normalized_name,
                "display_name": p.display_name,
                "source_channel": p.source_channel,
                "counterparty": p.counterparty,
                "members": [
                    {"descriptor": m.descriptor, "count": m.count} for m in p.members
                ],
            }
            for p in proposals
        ],
        indent=2,
    )
