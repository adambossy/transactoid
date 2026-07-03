# Penny

Penny is a personal-finance agent: it syncs bank transactions via Plaid,
categorizes them with an LLM against a two-level taxonomy, and answers
natural-language questions about the user's finances through a streaming
chat UI.

This branch is a ground-up rebuild of the prior "Transactoid" codebase on
top of two external packages by the same author:

- **[agent-harness](https://github.com/adambossy/agent-harness)** (Python) —
  the agent loop, model providers, sessions, sandboxes, skills, tool
  decorator. Penny never reimplements these.
- **[agent-ui](https://github.com/adambossy/agent-ui)** (React) — chat
  components (`Message`, `Composer`) speaking the Vercel AI SDK UI
  message-stream protocol.

## Layout

```
backend/
├── penny/
│   ├── api/            # FastAPI surface: main.py (POST /api/chat) + bridge.py
│   │                   #   (harness events → AI SDK SSE frames)
│   ├── agent_factory.py# builds the Agent: model, prompt render, toolsets
│   ├── tools/          # thin @tool wrappers the agent sees
│   │   └── _services/  # ported service implementations (categorizer, persister, sync…)
│   ├── plugins/amazon/ # self-contained Amazon toolset (scraping, login profiles)
│   ├── adapters/       # db (SQLAlchemy façade + models), cache, clients (plaid), storage (R2), amazon
│   ├── taxonomy/, rules/, memory/, services/, models/, utils/
│   ├── workspace.py    # ~/.transactoid workspace resolution ($PENNY_WORKSPACE)
│   ├── bootstrap.py    # idempotent create_schema + taxonomy seed
│   └── prompts.py      # promptorium-backed load_prompt()
├── .prompts/           # prompt source of truth (promptorium layout: <key>/<n>.md + _meta.json)
├── .agent/skills/      # agent-harness SkillRegistry discovery root (6 skills)
├── configs/taxonomy.yaml  # seed data, synced from prod via scripts/
└── scripts/
frontend/               # Vite + React 19 + @ai-sdk/react + @adambossy/agent-ui
```

## Dev loop

```bash
# Backend (from backend/). Use .env.test to point at the Neon test branch.
set -a && source .env.test && set +a
uv run uvicorn penny.api.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (from frontend/) — proxies /api to :8000
npm run dev
```

- **Local package dev is wired for both dependencies**: `pyproject.toml`
  has a `[tool.uv.sources]` editable path for `~/code/agent-harness`;
  `vite.config.ts` aliases `@adambossy/agent-ui` to
  `~/code/agent-ui/packages/agent-ui/src` (with `resolve.dedupe` for react —
  do not remove it, removing it causes a blank screen from a second React copy).
- **Backend restarts**: uvicorn `--reload` only watches `backend/` `*.py`.
  Edits to `.prompts/*.md` (lru_cached) and `~/code/agent-harness` need a
  manual restart.
- Logs: `~/.transactoid/logs/penny.log` (loguru file sink, DEBUG).

## Verification

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Run these before completing any unit of work. There is no mypy gate yet.

## Databases

- Default: SQLite at `backend/penny.db` (gitignored), schema via
  `bootstrap()` on startup (`Base.metadata.create_all` — no alembic
  migrations yet).
- Real data: Neon Postgres. `production` branch mirrors the Supabase prod
  DB; **never point a dev server at it**. Test against the `penny-test`
  Neon branch (`backend/.env.test`, gitignored). Recreate it from current
  prod with `neonctl branches delete/create --compute` (see .env.test
  header; note `neonctl connection-string --branch-name` returns the
  PARENT endpoint — a CLI bug — so build the URL from the branch's own
  endpoint host).

## Conventions

- **Prompts**: promptorium-managed, single source of truth in
  `backend/.prompts/<key>/<n>.md`; the central manifest is
  `backend/.prompts/_meta.json` (schema 2: per-key `source_file`,
  `version_dir`, `last_version`, `last_hash`). Everything loads through the
  thin `penny.prompts.load_prompt` facade (`promptorium.load_prompt`) — this
  branch deliberately uses that facade, not main's heavier `PromptService`
  machinery. The active system prompt is `penny-system-prompt`
  (`agent_factory._render_system_prompt` fills `{{CURRENT_DATE}}`,
  `{{DATABASE_SCHEMA}}`, `{{CATEGORY_TAXONOMY}}`, `{{AGENT_MEMORY}}`,
  `{{SQL_DIALECT*}}`).
  - Tweak the active prompt in place: edit `.prompts/<key>/<latest>.md`.
  - Substantive change: add a new version file `<n+1>.md` AND bump that
    key's `_meta.json` entry — `source_file`, `version_dir`, `last_version`,
    and `last_hash = "sha256:" + sha256 hex of the new file's bytes`.
  - Never hand-edit or renumber historical versions.
  - The promptorium MCP tools / CLI (`sync_prompts`, `track_prompt`,
    `update_prompt`) can manage tracking and keep `_meta.json` consistent.
- **Tools**: agent-facing wrappers in `penny/tools/*.py` are thin `@tool`
  async functions returning JSON-serializable dicts; implementations live in
  `tools/_services/`. Wrap sync service calls in `asyncio.to_thread`.
- **Tool output**: agent-harness puts dict/list returns on
  `ToolResult.structured_content` (MCP `structuredContent`); the bridge
  forwards it verbatim. Don't re-wrap tool output in `{"text": ...}`.
- **Env vars**: `PENNY_*` prefix (`PENNY_WORKSPACE`, `PENNY_CATEGORIZER_MODEL`,
  `PENNY_AGENT_*`). `.env` is gitignored; keep `.env.example` current.
- **Errors**: stream-level failures surface as `{type:"error"}` SSE frames →
  red banner in ChatScreen; tool failures as `tool-output-error` frames.
- **Workspace**: `~/.transactoid` (memory/, reports/, logs/) — path kept from
  the old product so user state carries over.
- **Single-user**: no auth, no multi-tenancy. That work is tracked in
  `plans/20260524-224025-productionize-transactoid.md`.
- **Branching**: `main` is the single long-lived branch. Cut feature
  branches off `main` (`<type>/<description>`, in a `.worktrees/<branch>`
  worktree) and merge them back into `main` — there is **no** `develop` /
  integration branch.
- **Observability (Langfuse)**: Penny uses **Langfuse** for all agent/LLM
  tracing. `penny.observability` is OpenTelemetry tracing exported
  to Langfuse over OTLP. The agent loop (chat + cron) is traced entirely by
  agent-harness's `OTELSubscriber` (an `EventBus` subscriber emitting GenAI
  semantic-convention spans) — Penny only wires the OTLP exporter and attaches
  the subscriber (`start_run_trace_task`). The categorizer (which bypasses the
  bus, calling the OpenAI/Gemini SDKs directly) is traced with the
  `categorizer_span` / `llm_generation` OTEL helpers. It's vendor-neutral:
  repoint the exporter at any OTLP backend. Turns on automatically when
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set (toggle via
  `PENNY_LANGFUSE_ENABLED`); strict no-op otherwise. See `.env.example`.

## Design rules

The north star is **managing complexity** — anything that makes the system hard
to understand or change. Every rule below serves that; when two seem to pull
apart, choose what leaves the next reader with less to hold in their head. These
sit on top of the **HARD CONSTRAINTS** in `AGENTS.local.md` (agent/website and
deploy/app segregation, the scheduler contract) — settle which domain you're in
and respect the one-directional deps first.

**Work strategically, not tactically.**

- Design is continual, not a phase. Spend the ~10–20% it takes to leave each
  module a little cleaner than the expedient path would; a run of tactical
  shortcuts is how this codebase would rot.
- **Design it twice.** For anything non-trivial — a new tool surface, a schema,
  a module boundary — sketch two approaches before committing. The second almost
  always sharpens the first.

**Make modules deep.**

- A good module hides a lot behind a small interface: the functionality
  (benefit) should dwarf the interface and concepts a caller must learn (cost).
  Penny already leans this way — thin `@tool` wrappers over deep
  `tools/_services/`; the `penny.adapters.db` facade over SQLAlchemy. Extend that
  pattern; don't invert it.
- **Pull complexity downward.** When something is hard, the module should absorb
  it rather than hand it up through its interface — handle the special case, the
  retry, the odd Plaid field *inside* the service so no caller re-handles it.
  Simple interface + complex implementation is a good trade; the reverse is a
  red flag.
- **Distrust shallow modules and pass-throughs.** A function whose interface is
  nearly as complex as its body, a method that only forwards to another, a
  variable threaded untouched through many layers — collapse them.

**Hide information; don't leak it.**

- Each module owns a design decision and conceals it (a schema detail, the Plaid
  wire format, the R2 layout, an SQL-dialect quirk). Two modules encoding the
  same decision is *leakage* — the source of change-amplification.
- **Different layer, different abstraction.** If adjacent layers traffic in the
  same concepts, one probably shouldn't exist. `api/` speaks HTTP/streaming,
  `services/` orchestration, `tools/_services/` finance operations, `adapters/`
  I/O — each raises the abstraction of the one below. Reach *down* a layer, never
  up or sideways into a peer's internals.
- **Finance data goes through the `penny.adapters.db` facade; app data never
  does.** Keep the facade finance-only; website/app state gets its own
  `Base`/models/engine/store in a separate schema/db (`AGENTS.local.md`).
  Information hiding and a segregation constraint at once.

**Design interfaces for the common case.**

- **Prefer somewhat general-purpose interfaces.** A slightly more general
  interface is usually simpler and deeper than a narrow one — define the
  *operation*, not one caller's use of it. This is *not* speculative generality:
  generalize the interface, not the feature set; add the knob/parameter when the
  second real caller exists, and delete machinery nothing uses.
- **Define errors out of existence.** The cheapest exception is the one that
  can't happen. Shape APIs so routine conditions aren't exceptional — return
  empty, be idempotent, make the no-op safe (`bootstrap()` is idempotent and
  sync is re-runnable on purpose). Fewer exception sites, less complexity.
- **Genuine failures still surface — never hide.** When something is truly
  wrong, let it propagate to a defined seam (`{type:"error"}` frames,
  `tool-output-error`, non-zero CLI exit) rather than swallowing it or returning
  a sentinel "success". Defining errors out of existence removes *spurious*
  exceptions by design; it never means silencing *real* ones.

**Make it obvious.**

- A reader should form correct expectations without deep study; obscurity and
  cleverness are complexity. Consistency is the lever — match the surrounding
  module's naming, structure, and idioms so new code reads as if it were always
  there. A new convention is a cost everyone pays.
- **Name precisely and reuse existing terms.** A name that's vague or hard to
  choose signals a fuzzy abstraction — fix the design, not just the label. Reuse
  the codebase's vocabulary (transaction, descriptor, category, period…) rather
  than minting synonyms.
- **Comments capture what code can't.** Write for the non-obvious — the *why*,
  the invariant, the abstraction a caller needs — not a paraphrase of the
  mechanics; match the file's existing comment density.

**Reuse, and keep one source of truth.**

- **Don't reimplement the libraries.** The agent loop, providers, sessions,
  sandboxes, skills, and tool decorator are agent-harness; the chat UI is
  agent-ui. Wrap or extend — never fork their responsibilities into Penny.
- **Single source of truth.** Every value has one home: prompts in `.prompts/`,
  taxonomy seed in `configs/taxonomy.yaml`, runtime/deploy config in the
  `PENNY_*` contract via `config.py`. Reference it; copying is leaked information
  waiting to drift.
- **Config is the only cross-domain seam.** Environment-varying behaviour reads
  a `PENNY_*` var; code never branches on deployment topology or names a
  deployable.

**Keep change safe.**

- Prefer subtraction: delete dead code rather than route around it; retire an
  abstraction that no longer earns its interface.
- Small, dependency-ordered commits; idempotent bootstrap/migrations; no
  irreversible data/infra op without a snapshot or escape hatch. Reversibility
  is what lets you refactor strategically without fear.

## Requirements (`REQUIREMENTS.txt`)

`REQUIREMENTS.txt` (repo root) is the living spec: **what Penny must do**
(Product / Functional) and the **non-negotiable rules it must hold** (Technical
Invariants / Constraints). It states *what* and *why*, not *how* — no file
paths or implementation detail that this file or `AGENTS.local.md` already own;
link to the enforcing guardrail (e.g. `test_deploy_segregation.py`) when a rule
has one.

Maintain it **in the same change** that alters reality:

- Add/change/remove a user-facing behaviour → update the Product section.
- Add/relax/remove an invariant or constraint → update the Technical section.
- Reviewers treat `REQUIREMENTS.txt` as the scope-of-record: a behavioural or
  constraint change not reflected there is an **incomplete** change.

## Gotchas

- The Plaid Link flow (`connect_new_account`) runs a localhost HTTPS server
  and opens a browser — works only when backend runs on the user's machine.
  Remote deployment requires the redirect rearchitecture in the
  productionization plan (B-6).
- Gemini rejects JSON schemas containing `additionalProperties` etc.; the
  harness strips them (`providers/google.py`). If a new tool 400s on Gemini,
  check its generated schema first.
- `run_sql` is intentionally unrestricted (read AND write) per explicit
  decision; tightening is a productionization item.
