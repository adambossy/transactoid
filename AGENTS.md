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
  machinery. The active system prompt is `agent-loop`
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
