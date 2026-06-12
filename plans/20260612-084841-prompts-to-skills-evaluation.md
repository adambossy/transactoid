# Prompts → Skills Evaluation

**Date:** 2026-06-12
**Branch:** feature/mvp-rebuild
**Scope:** ANALYSIS ONLY. No prompts or skills are modified. This document
recommends which `backend/.prompts/<key>` prompts should become agent skills
under `backend/.agent/skills/<name>/SKILL.md`.

## How the decision was made

The key discriminator is *when* the prompt is consumed:

- **Always-on / injected:** rendered into the live system prompt at startup, or
  injected as a fragment into another prompt. These must stay prompts — a skill
  is loaded progressively and would never be "always present."
- **Build/pipeline-time:** loaded by a tool or service (not the agent) as a
  template for a deterministic LLM call. These stay prompts; they are template
  strings with `{{...}}` placeholders filled by Python, not procedures the agent
  reasons through.
- **Session-time, on-demand procedure:** the agent would load it when a user
  asks for a specific workflow ("give me my weekly report", "what did I spend
  yesterday"). These are the natural skill candidates — multi-step procedures
  with branching, file I/O, and tool hand-offs.

Code evidence gathered (`grep` over `backend/penny/`):

- `penny-system-prompt` → `agent_factory.py:111` (rendered at startup).
- `sql-directives-{dialect}` → `agent_factory.py:96` (injected into the system
  prompt via `{{SQL_DIALECT_DIRECTIVES}}`).
- `categorize-transactions` + `taxonomy-rules` → `categorizer.py:551/554/567`
  (loaded by the categorizer **service**, not the agent).
- `generate-memory-index` → `memory/index_generation.py:172` (loaded by a
  service that regenerates `memory/index.md`).
- `report-weekly`, `report-weekly-jenny`, `report-monthly`, `report-annual`,
  `report-daily`, `report-md-to-html` → **no code references anywhere**. They
  are orphaned in the rebuild and still point at the old `src/transactoid/...`
  paths and `execute_shell_command`. They are clearly meant to be invoked by the
  agent on user request.

## Summary recommendation table

| Prompt key | Verdict | Rationale (one-liner) |
|---|---|---|
| `penny-system-prompt` | **Keep as prompt** | The always-on system prompt rendered at startup; by definition cannot be progressively loaded. |
| `sql-directives-postgresql` | **Keep as prompt** | Dialect boilerplate injected into the system prompt (`{{SQL_DIALECT_DIRECTIVES}}`); a fragment, not a procedure. |
| `sql-directives-sqlite` | **Keep as prompt** | Same — the SQLite variant of the injected dialect fragment. |
| `categorize-transactions` | **Keep as prompt** | A pipeline-time template the categorizer *service* fills and sends to the LLM; the agent never runs it. |
| `taxonomy-rules` | **Keep as prompt** | Injected into `categorize-transactions` as `{{TAXONOMY_RULES}}`; data, not a workflow. (Migrations are already covered by `migrate-taxonomy`.) |
| `generate-memory-index` | **Keep as prompt** | A service-time template filled by `index_generation.py`; deterministic, not agent-invoked. |
| `report-md-to-html` | **Already covered** | Duplicates the existing `render-report-html` skill (md → styled HTML). |
| `report-weekly` | **Convert to skill** | On-demand user workflow: gather data, build sections, render HTML, write to workspace. |
| `report-monthly` | **Convert to skill** | Same shape as weekly with a monthly window; clear user-invoked report procedure. |
| `report-annual` | **Convert to skill** | Same shape with an annual window and YoY/quarterly trends; user-invoked. |
| `report-daily` | **Convert to skill** | User-invoked "yesterday + rolling/projection" report; markdown-only procedure. |
| `report-weekly-jenny` | **Convert to skill** (low priority / consider data-driven config instead) | A user-invoked report that also emails a named recipient; a real workflow, but the hard-coded recipient suggests it may belong as parameters rather than a checked-in skill. |

**Net:** 4 clear conversions (`report-weekly`, `report-monthly`, `report-annual`,
`report-daily`), 1 conditional (`report-weekly-jenny`), 1 already-covered
(`report-md-to-html`), 6 keep-as-prompt.

A strong alternative worth flagging: the four periodic reports share ~80% of
their structure. They could collapse into **one** `spending-report` skill
parameterized by period (daily / weekly / monthly / annual) rather than four
near-duplicate skills. See the per-candidate notes.

---

## Keep-as-prompt details

### `penny-system-prompt`
The live system prompt, rendered once at startup by
`agent_factory._render_system_prompt` (fills `{{CURRENT_DATE}}`,
`{{DATABASE_SCHEMA}}`, `{{CATEGORY_TAXONOMY}}`, `{{AGENT_MEMORY}}`,
`{{SQL_DIALECT*}}`). It is *the* always-present context. A skill is loaded
progressively mid-session for a specific request; turning the system prompt into
a skill is a category error. Keep.

### `sql-directives-postgresql` / `sql-directives-sqlite`
Each is a short dialect fragment injected into `penny-system-prompt` at
`{{SQL_DIALECT_DIRECTIVES}}` (`agent_factory.py:96`). They are not standalone
procedures and have no "when to use" trigger — they are always in scope whenever
the agent writes SQL. Keep as prompts. (Note: both currently hard-code
`Current date: 2026-06-11` in their worked examples; that is a prompt-hygiene
issue, out of scope for this analysis.)

### `categorize-transactions`
Loaded by the categorizer **service** (`categorizer.py:551`), not the agent. It
is a template with `{{TAXONOMY_HIERARCHY}}`, `{{CTV_JSON}}`, `{{MERCHANT_RULES}}`,
`{{TAXONOMY_RULES}}` that Python fills and sends to the model during sync, with
versioning tracked for cache keys (`categorizer.py:849-853`). This is
build/pipeline-time, not a user-invoked workflow. Keep.

### `taxonomy-rules`
Injected into `categorize-transactions` as `{{TAXONOMY_RULES}}`
(`categorizer.py:554/567`) and describes the taxonomy in natural language. It is
reference data consumed by another prompt, not a procedure. The *action* of
changing the taxonomy is already a skill (`migrate-taxonomy`), and that skill
already lists updating the taxonomy-rules prompt as one of its propagation
steps — so there is no separate skill to extract here. Keep as prompt.

### `generate-memory-index`
Loaded by `memory/index_generation.py:172` to regenerate `memory/index.md` from
a tree snapshot and git-tracked file list. It is a service-time template
(`{{MEMORY_TREE}}`, `{{TRACKED_MEMORY_FILES}}`, `{{RUNTIME_TAX_RETURN_FILES}}`),
deterministic and not agent-invoked. Keep.

### `report-md-to-html` — Already covered by `render-report-html`
This prompt converts a markdown report to a full HTML document — exactly what the
existing `render-report-html` skill does, but with less structure (the skill ships
a complete CSS system and HTML-structure checklist). The two overlap directly.
Recommendation: do **not** create a skill for this; if anything, retire the
prompt in favor of the skill. The only nuance is that `report-md-to-html` targets
"inline-safe for email clients" while `render-report-html` uses a `<style>` block
in `<head>` — if email-client inlining matters, that belongs as a variant inside
`render-report-html`, not as a separate skill.

---

## Convert-to-skill candidates

> Shared prerequisite for all report skills: they query `derived_transactions`
> (per the two-table rule in the system prompt), optionally read
> `memory/budget.md`, hand off to the `render-report-html` skill for HTML, and
> write into the workspace `reports/` directory. The current prompts reference
> stale paths (`src/transactoid/skills/...`, `.transactoid/reports/...`) and
> `execute_shell_command`; any conversion must update these to the rebuild's
> workspace tools and skill location (`backend/.agent/skills/render-report-html`).
> **Migration risk (all):** the prompts are unreferenced in code, so converting
> them is low-blast-radius, but it also means there is no current trigger path —
> the skills' `when_to_use` triggers become the *only* invocation mechanism, so
> they must be written precisely.

### Option A (recommended): one consolidated skill

**Skill name:** `spending-report`

**when_to_use:** When the user asks for a spending report or summary over a
period — daily, weekly, monthly, or annual ("how did I do this week", "give me
my monthly report", "year in review").

**Body outline:**
- Inputs: `period` (daily | weekly | monthly | annual), optional `as_of_date`.
- Resolve the window and the comparison baseline per period (daily: 7/14-day
  rolling + prior-month windows + 30-day centered projection; weekly: vs last
  week + 4/8/12-week trends; monthly: vs last month + 3/6/12-month trends;
  annual: YoY + quarterly seasonality).
- Budget step: if `memory/budget.md` exists, derive the period target from the
  stored monthly figures (weekly ÷ 4.33, monthly ×1, annual ×12); otherwise omit
  budget columns.
- Canonical sections: Executive Summary, Category Breakdown, Trends, Unusual /
  Major Expenses, Predicted Upcoming, Actionable Recommendations (daily uses its
  own leaner section list).
- "Unusual" heuristics ( >$500 non-recurring, new merchant >$100, category 50%+
  over baseline, same-day duplicate) parameterized by the period's baseline.
- Output: markdown report in the reply; for non-daily, hand off to
  `render-report-html` and write `reports/report-<period>-latest.html`.

**Prerequisite:** `render-report-html` skill (exists); `memory/budget.md`
optional; workspace write access (exists).
**Migration risk:** Must faithfully preserve each period's distinct trend math
and section list; the daily report's projection logic is the most intricate and
easiest to get wrong when merged. A single skill with per-period branches keeps
the shared 80% in one place at the cost of a longer SKILL.md.

### Option B: four separate skills (mirror the prompts 1:1)

If you prefer to keep each report self-contained (and avoid a large branching
skill), create one skill per period. They share the structure above; the
per-period specifics:

#### `weekly-spending-report`
- **when_to_use:** When the user asks for a weekly spending report/summary.
- Window: this week vs last week; trends at 4/8/12 weeks; weekly budget = monthly
  ÷ 4.33; sections 1–6 as in `report-weekly`; render HTML and write
  `reports/report-weekly-latest.html`.

#### `monthly-spending-report`
- **when_to_use:** When the user asks for a monthly spending report/summary.
- Window: this month vs last month; trends at 3/6/12 months; budget = monthly ×1;
  same 6 sections; render HTML, write `reports/report-monthly-latest.html`.

#### `annual-spending-report`
- **when_to_use:** When the user asks for an annual / year-in-review report.
- Window: this year vs last year; YoY + quarterly seasonality trends; budget =
  monthly ×12; adds "year-ahead planning"; render HTML, write
  `reports/report-annual-latest.html`.

#### `daily-spending-report`
- **when_to_use:** When the user asks "what did I spend yesterday" or for a daily
  report.
- Leaner, markdown-only: Yesterday at a Glance, Yesterday Transactions +
  category context, 3–5 recommendations, 7/14-day rolling totals, prior-month
  comparison windows, and a 30-day centered sliding projection (15 back / 15
  forward), plus per-category 7/14-day + projection. No HTML hand-off in the
  current prompt.

**Migration risk (Option B):** four near-duplicate skills drift over time; a
change to the shared "unusual" heuristics or budget-derivation math must be made
in four places. This is the main argument for Option A.

### `report-weekly-jenny` — Convert, but reconsider the shape (low priority)

**Skill name (if converted as-is):** `weekly-report-email-jenny`
**when_to_use:** When the user asks to generate and email Jenny's weekly spending
summary.
**Body outline:** like the weekly report but (a) email-first HTML with inline-CSS
colored budget-delta cells (six-shade scale), (b) a per-transaction cumulative-MTD
+ budget-delta detail table, (c) friendly "we"-voiced recommendations, and
(d) a final step that writes `reports/report-weekly-jenny-latest.html` and emails
the result via `send_email_report` to a fixed recipient.

**Prerequisite:** `send_email_report` tool (exists, `tools/delivery.py`);
optional `memory/budget.md`.
**Migration risk / caveat:** The recipient address and subject are hard-coded in
the prompt. Baking a named third party into a checked-in skill is awkward for a
single-user product and doesn't generalize. Prefer either (a) folding this into
the consolidated `spending-report` skill with `recipient`/`subject`/`tone`
parameters and a "colored-email" variant, or (b) representing it as user-specific
config/memory rather than a skill. If a standalone skill is desired for
convenience, convert it but flag the hard-coded recipient as a known wart.

---

## Recommended next steps (not performed here)

1. Adopt **Option A** (`spending-report`) unless there's a reason to keep reports
   physically separate; it minimizes duplication of the shared report scaffolding.
2. Retire `report-md-to-html` in favor of `render-report-html`; if email-client
   CSS inlining is required, add it as a variant inside that skill.
3. When converting, fix the stale `src/transactoid/...` / `.transactoid/...` /
   `execute_shell_command` references to the rebuild's workspace + skill paths.
4. Keep all six prompt-classified keys exactly where they are.
