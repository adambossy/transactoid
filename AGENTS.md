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

## Canonical vs. non-canonical artifacts

Everything checked in is one of two kinds, and reading the repo correctly means
knowing which you're looking at:

- **Canonical** — the current source of truth: what defines how Penny runs in
  production *today*. Backend/frontend code, `deploy/`, the prompts in
  `.prompts/`, the taxonomy seed, `REQUIREMENTS.txt`, and these agent docs are
  canonical. Keep it correct and current; if canonical says something false,
  that is a bug.
- **Non-canonical** — point-in-time records kept for **history, not truth**.
  Often accurate at inception, they drift as the system moves on. We keep them
  deliberately: to reconstruct *what happened and why* when debugging, doing
  archaeology, or tracing the lineage of a design. They are **not** a reliable
  account of how the code works now.

Examples of non-canonical artifacts:

- **Plans** (`plans/`) — a plan captures intent at a moment. Once the work lands
  or changes course, the plan is a historical record, not a spec: don't read it
  as the current design, and don't rewrite old plans to match reality.
- **Migration / cut-over scripts** — one-off code written to *execute* a
  transition (especially non-database ones: reorganizing files, re-pointing
  infra, backfilling a workspace). Their worth is the record of the exact steps
  taken, not how production runs day to day. (Numbered schema migrations under
  `backend/db/migrations/` are a distinct, tracked mechanism — not the one-off
  cut-over scripts meant here.)
- **Transient one-off tooling** (`backend/transient/**`) — self-contained
  one-shot tools such as the phase-3 account cutover (`backend/transient/
  account-cutover/`). This tree is **non-canonical**: excluded from the
  ruff/pytest gates (ruff `extend-exclude`; pytest `testpaths` never reaches
  it), exempt from the "follow existing patterns" expectations, and **deletable**
  once spent. It may import canonical app models/façade/cipher **read-only**; no
  app code imports it. Treat it as scratch held to its own rehearsal/verify bar.

Directives:

- **Canonical wins.** When a non-canonical artifact disagrees with canonical
  code, the code is right and the artifact is stale by default.
- **Keep the history; don't delete it.** A superseded plan or a spent cut-over
  script stays as a record — removing it erases the lineage we keep it for.
- **Segregate; never intermingle.** Non-canonical artifacts live in clearly
  non-canonical locations: plans in `plans/`, and spent one-off / cut-over
  scripts archived *out of* the canonical packages and apart from the recurring
  dev tooling in `backend/scripts/`. A spent one-off must not sit in a canonical
  package as if it still runs.
- **Don't maintain non-canonical code.** It is frozen: we don't refactor it, fix
  its lint, or keep it building, and it stays out of the canonical verification
  gate.

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
# Backend — run against the session Neon test branch via pennydb (from repo root).
backend/scripts/pennydb test exec -- uv run uvicorn penny.api.main:app --host 127.0.0.1 --port 8000 --reload
# (classic equivalent, from backend/: set -a && source .env.test && set +a && uv run uvicorn …)

# Frontend (from frontend/) — proxies /api to :8000
npm run dev
```

- **agent-harness is a pinned git dep** (`@v0.2.0` in `[project.dependencies]`),
  so `uv sync --frozen` installs the exact same set in dev, CI, and prod — the
  lockfile is portable (no machine-local editable path). To hack on
  agent-harness locally, opt in **per-machine** without touching the committed
  lock: `uv sync --frozen && uv pip install -e ~/code/agent-harness` (re-run the
  editable install after any `uv sync`, which reverts it to the pinned version).
- **agent-ui** live-dev is still wired via `vite.config.ts`, which aliases
  `@adambossy/agent-ui` to `~/code/agent-ui/packages/agent-ui/src` (with
  `resolve.dedupe` for react — do not remove it, removing it causes a blank
  screen from a second React copy).
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

The multi-tenant RLS suites (`@pytest.mark.postgres`) skip unless
`POSTGRES_TEST_URL` is set — point it at the Neon `penny-test` branch or a
local Postgres with a **non-superuser** role (superusers bypass RLS; see
`tests/conftest_postgres.py`):

```bash
POSTGRES_TEST_URL=postgresql://... uv run pytest -q -m postgres
```

## Databases

- **One schema authority per environment.** SQLite (dev/test/eval) builds the
  schema from the models via `create_all` (fast, model-accurate) — default
  `backend/penny.db` (gitignored), created by `bootstrap()` on startup.
  **Postgres is owned exclusively by alembic**: `bootstrap()` never touches a
  Postgres schema, and `create_all` is *refused* there (`DB.create_schema` /
  `create_web_schema` raise on a non-SQLite engine). `create_all` only creates
  *missing tables* — it never `ALTER`s or advances `alembic_version`, so on a
  durable Postgres DB it would be a second, silent authority that collides with
  the migration chain (the phase-3 cutover root cause).
- Schema evolution: alembic migrations live in `backend/db/migrations/`
  (`version_locations` in `backend/alembic.ini`). They evolve the Postgres
  schema and are applied by `penny migrate` (`alembic upgrade head`), run once
  per deploy via the backend `release_command` (`deploy/backend/fly.toml`) in
  an ephemeral machine before the app machines roll. A drift test
  (`tests/test_schema_drift.py`) asserts the models and the chain agree. See
  `docs/superpowers/plans/2026-07-09-alembic-sole-authority-on-postgres.md`.
- Real data: Neon Postgres. `production` branch mirrors the Supabase prod
  DB; **never point a dev server at it**. Test against a fresh one-off test
  branch: `pennydb test refresh` (wraps `scripts/new_test_branch.sh`; writes
  `~/.transactoid/env.test`, shared by all worktrees, with
  `backend/.env.test` as a symlink to it).
- **Database access goes through `backend/scripts/pennydb`** — the target is
  the mandatory first argument, and every invocation banners which DB it's
  touching. `pennydb test psql|url|exec|refresh` for dev work (the default in
  Claude sessions; allowlisted). `pennydb prod psql` is read-only and always
  permission-prompted; writes need `pennydb prod psql --write`. Raw `psql` /
  `neonctl connection-string` are denied in sessions (`.claude/settings.json`)
  — and raw `neonctl connection-string --branch-name` has two traps anyway: it
  returns the PARENT endpoint for child branches (CLI bug), and `production`
  now requires `--role-name neondb_owner` (multiple roles exist).

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
- **Tenancy**: every financial row carries `household_id` / `owner_user_id` /
  `visibility`, enforced by Postgres RLS (USING + WITH CHECK, incl. the agent's
  `run_sql`) plus app-level filtering (the only layer on SQLite dev). The
  per-request principal is a `RequestContext` (`penny/tenancy/`), resolved by
  a dev stub (`X-Penny-*` headers / `PENNY_DEV_*` env) until real auth lands
  in phase 2. Plaid access tokens are encrypted at rest
  (`PENNY_PLAID_TOKEN_KEY`).
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

## Architecture: layered domains

The target architecture — where the code is heading — is the layered-domain
model from OpenAI's harness-engineering work: within a domain, code lives in a
fixed stack of layers whose dependencies flow in **one direction only**.

    Types → Config → Repo → Service → Runtime → UI

A layer may depend only on layers to its **left** — never rightward, never
sideways into a peer's internals.

- **Types** — pure domain data shapes (models, enums, DTOs, schemas). No
  behaviour, no I/O; depends on nothing.
- **Config** — static configuration and constants, typed by Types (Penny's
  `PENNY_*` contract read through `config.py`).
- **Repo** — data access / persistence: reads and writes the store behind a
  repository interface, hiding SQL and schema (Penny's `penny.adapters.db`
  façade).
- **Service** — business logic and orchestration over repos (`tools/_services/`:
  categorizer, sync, persister, …). No HTTP, no framework, no I/O primitives.
- **Runtime** — the surfaces that drive services: the FastAPI app (`api/`), the
  Typer CLI (`cli.py`), the cron entrypoints. Wires a request/job to a service.
- **UI** — presentation (`frontend/`), consuming Runtime outputs.

**Providers — the single seam for cross-cutting concerns.** Auth, external
connectors (Plaid, R2, Amazon), telemetry (Langfuse), and feature flags enter
through explicit provider interfaces, injected into the layer that needs them.
A layer *takes* a provider; it never reaches sideways to import one ad hoc.

This axis is orthogonal to the domain-segregation HARD CONSTRAINTS in
`AGENTS.local.md`: segregation says which *domain* code belongs to (agent /
website / deploy); this says which *layer* within a domain. It also makes the
Design-rules "different layer, different abstraction" bullet concrete. OpenAI
enforces the dependency direction with custom linters + structural tests; Penny
has no such guardrail yet, so for now it rests on you and review. Source:
[Harness engineering](https://openai.com/index/harness-engineering/).

### The campfire rule — leave it better than you found it

**Penny does not yet adhere to this architecture.** The layers exist only
informally and are crossed in places — e.g. the `penny.adapters.db` façade
blends Types (models) and Repo (data access), and cross-cutting connectors
(Plaid, R2, Langfuse) are imported where they're used rather than injected
through a Providers seam. We converge on the target the way the source does:
continuous small refactors, not a big rewrite.

- **When you touch out-of-alignment code, nudge it toward the target** — move a
  misplaced responsibility into its layer, thread a cross-cutting dependency
  through a provider, split a blended module. Leave the campground cleaner than
  you found it.
- **Flag misalignments you notice but don't fix** (a short comment, or a note in
  the PR) so the drift is visible and can be scheduled.
- **Stay in scope — this is a hard limit, not a suggestion.** Refactor only what
  your task already touches, and only as far as the task needs. Do **not** open
  unrelated files to "fix the architecture," chase a refactor across the tree,
  or let alignment work balloon the diff or the risk of the change. If a
  worthwhile refactor is bigger than the task, flag it and leave it for its own
  change — a small in-scope improvement beats a sprawling one that derails the
  work.

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
- `run_sql` is read-only. An input-layer parse guard
  (`security/sql_read_guard.py`) accepts only a single read-only `SELECT` and
  rejects any write/DDL/session statement before execution; in prod it also runs
  on a dedicated read-only Postgres role under RLS (see `REQUIREMENTS.txt` T2a /
  T8). Older notes calling it "unrestricted (read AND write)" are stale.
