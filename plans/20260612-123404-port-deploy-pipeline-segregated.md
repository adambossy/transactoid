# Port the deployable pipeline into a segregated `deploy/` domain

Status: proposed
Branch: `feature/mvp-rebuild`
Author: planning pass (Penny)

## Goal

Bring the working release/runtime pipeline that lives on the old `main`
branch (the Fly main app + the Fly cron-manager + the CI deploy workflow)
into the `feature/mvp-rebuild` codebase **without** scattering Dockerfiles,
`fly.toml`s, and deploy scripts across the application tree.

Deploy becomes a **fifth segregated domain** alongside the four the repo
already keeps apart (agent-harness lib, agent-ui lib, the agent, the
website/API). Everything release- and runtime-shaped lives under a single
top-level `deploy/` directory; `backend/` and `frontend/` stay **pure
application code** with zero deploy artifacts inside them.

The interface between deploy and app is exactly one thing: the
**env/config contract** (`backend/penny/config.py` + `.env.example`). Deploy
supplies values; the app reads them. Nothing else crosses the seam.

## Current state (what exists on `main`, enumerated)

The old pipeline is a two-Fly-app topology plus a CI driver. Verified by
reading each file on `main`:

1. **`Dockerfile`** (repo root) — multistage `uv` build for the
   sync/run job container. Builder stage installs `git` (needed for git
   deps), `pip install uv`, then `uv sync --frozen --no-dev --extra
   stagehand` (the `stagehand` extra pulls Browserbase for the Amazon
   scraper). Copies `src/ models/ .prompts/ prompts/ configs/ scripts/
   evals/`, `uv pip install --no-deps -e .`. Production stage installs
   `libpq5`, copies the venv + source, sets `PATH=/app/.venv/bin`.
   Entrypoint runs the `transactoid` CLI.

2. **`fly.toml`** (repo root) — `app = "transactoid"`, `primary_region =
   "iad"`, `[build] dockerfile = "Dockerfile"`, an `[env]` block carrying
   `TRANSACTOID_AGENT_PROVIDER/MODEL` + `TRANSACTOID_CATEGORIZER_MODEL`
   (all `gemini-3.5-flash`), `[[vm]] 1024mb` (512mb was OOM-killed). No
   HTTP service — it is a scheduled job image.

3. **`ops/cron-manager/`** — the **second** Fly app:
   - `Dockerfile`: `FROM registry.fly.io/transactoid-cron-manager:<digest>`
     then `COPY ops/cron-manager/schedules.json /usr/local/share/schedules.json`.
   - `fly.toml`: `app = "transactoid-cron-manager"`, a `/data` mount,
     `256mb` VM.
   - `schedules.json`: an array of cron entries (daily 10:00 UTC report,
     weekly Saturday report). **Each entry embeds its own `config.env`**
     (`TRANSACTOID_WORKSPACE`, `TRANSACTOID_AGENT_PROVIDER/MODEL`,
     `TRANSACTOID_CATEGORIZER_MODEL`) **and `config.image`** (a pinned
     `registry.fly.io/transactoid:deployment-…` digest), plus guest sizing,
     a `transactoid_workspace` volume mount, and the command
     (`transactoid run-scheduled-report` / `transactoid run --prompt-key …
     --email …`).

4. **`scripts/sync_cron_manager.sh`** — the cron deploy driver. Ensures the
   `transactoid_workspace` volume exists, resolves its **volume id**,
   resolves the **latest app image** from `fly releases` (deliberately not
   `fly machines list`, which can surface a stale ephemeral cron image),
   `jq`-renders both into `schedules.json` in place, `fly deploy`s the
   cron-manager with that file baked in, then `git checkout`s the file to
   discard the rendered mutation.

5. **`scripts/seed_workspace_volume.sh`** — clones the private
   `transactoid-workspace` repo onto the shared Fly volume so cron runs
   start with `memory/` + `reports/` populated.

6. **`Makefile`** — `fly-sync-cron`, `fly-deploy-and-sync-cron`
   (`fly deploy --app transactoid` → sync cron → seed workspace),
   `fly-seed-workspace`.

7. **`.github/workflows/deploy-and-sync-cron.yml`** — on push to `main`,
   a daily pre-report cron (`40 8 * * *`), and `workflow_dispatch`. Sets up
   Python/uv/flyctl, aliases `fly`→`flyctl`, installs a workspace deploy
   SSH key, then runs `make fly-deploy-and-sync-cron`. Auth via a single
   `FLY_API_TOKEN` secret that must cover **both** Fly apps.

8. **`.dockerignore`** (repo root) — standard Python ignores plus repo
   specifics (`.worktrees`, `.transactions`, `*.db`, web `node_modules`,
   etc.).

### What the branch looks like today (the new deployable shapes)

There is **no** deploy infra on the branch (`.github/` absent, no
Dockerfile, no `fly.toml`). The deployables have changed shape:

- **Backend** — a long-running FastAPI service: `uvicorn
  penny.api.main:app` (`backend/penny/api/main.py`). It bootstraps the
  schema on startup and streams the agent over SSE. **This is a web
  service, not a one-shot job** — a material change from `main`'s job image.
- **Frontend** — `frontend/` is a Vite + React 19 app; production artifact
  is a **static build** (`npm run build` → `dist/`). It proxies `/api` to
  the backend in dev; in prod it needs the API reachable at a real origin.
- **Cron-manager** — conceptually unchanged (a Fly cron-manager app reading
  `schedules.json`), **but** the headless commands it used to run
  (`transactoid run-scheduled-report`, `transactoid sync …`) **do not exist
  on the branch yet** — there is no Typer CLI and no scheduled-report entry
  point. See Risks/open questions.

Branch dependency facts that affect remote builds (`backend/pyproject.toml`):
- `requires-python = ">=3.13"`.
- `agent-harness[anthropic,openai,google]` is declared as a git dep in
  `[project.dependencies]` **but overridden** by `[tool.uv.sources]` to an
  **editable local path** `/Users/adambossy/code/agent-harness`. That path
  does not exist in a remote builder → the build fails unless we strip/flip
  the source for the deployed build.
- `promptorium-python @ git+…@main` — a git dep; resolvable in-container as
  long as `git` is installed in the builder.
- `stagehand>=0.5.9` is a top-level dep here (not gated behind an extra as
  on `main`); the Browserbase backend comes along by default.

App-side config contract today: `backend/.env.example` (the `PENNY_*` +
provider/Plaid/R2/Resend/DB vars) and `backend/penny/config.py`
(`load_runtime_config_from_env`, `PENNY_AGENT_*`). Note the env **prefix
changed** `TRANSACTOID_*` → `PENNY_*`, and the workspace var is now
`PENNY_WORKSPACE` (default still `~/.transactoid`).

## Target `deploy/` layout

```
deploy/
├── README.md                  # the seam doc: how deploy consumes the app
├── env/
│   └── deploy.env.template     # SINGLE SOURCE OF TRUTH for runtime env.
│                               #   PENNY_* + provider/DB values shared by
│                               #   backend fly [env] AND cron config.env.
├── backend/
│   ├── Dockerfile              # multistage uv build of the FastAPI service
│   ├── fly.toml                # app = "penny" (or "transactoid"); HTTP svc
│   └── .dockerignore           # build-context ignores for the backend image
├── frontend/
│   ├── Dockerfile              # node build → static server (or build-only)
│   ├── fly.toml                # app = "penny-frontend" (static/HTTP)
│   └── .dockerignore
├── cron-manager/
│   ├── Dockerfile              # FROM registry.fly.io/<cron>:<digest> + COPY schedules.json
│   ├── fly.toml                # app = "penny-cron-manager"
│   └── schedules.json          # cron entries; config.env GENERATED, not hand-edited
└── scripts/
    ├── deploy_backend.sh        # fly deploy --config deploy/backend/fly.toml ...
    ├── deploy_frontend.sh       # fly deploy --config deploy/frontend/fly.toml ...
    ├── sync_cron_manager.sh     # ported; renders schedules.json + deploys cron app
    ├── render_cron_env.sh       # NEW: emits cron config.env from env/deploy.env.template
    └── seed_workspace_volume.sh # ported; seeds the shared Fly volume
```

Repo-root files that **stay at root** (GitHub / tooling requirements):

```
.github/workflows/
└── deploy.yml                  # THIN shim: checkout + flyctl, then call
                                #   deploy/scripts/*.sh. No deploy logic inline.
```

Everything in `backend/` and `frontend/` remains application code. No
`Dockerfile`, no `fly.toml`, no deploy script lives under either.

## The deploy↔app seam + the one-directional dependency rule

**Rule: `deploy/` → app, never the reverse.**

- **Build-time coupling** is allowed and one-directional: Dockerfiles under
  `deploy/<x>/` `COPY` from `../backend` / `../frontend`. The build context
  is the **repo root** (so the Docker build can see both `deploy/` and the
  app trees); invoked as `fly deploy --config deploy/<x>/fly.toml
  --dockerfile deploy/<x>/Dockerfile` with the repo root as context. Each
  `deploy/<x>/.dockerignore` trims that context per image.
- **Runtime coupling** is exactly the **env/config contract**. The app
  reads `PENNY_*` via `backend/penny/config.py` and `os.environ`; deploy
  supplies them via fly `[env]`, fly secrets, and the cron `config.env`.
  `deploy/env/deploy.env.template` is the canonical list; `backend/.env.example`
  remains the app-side mirror for local dev.
- **Forbidden (enforced by review + a guardrail test):**
  - App code (`backend/`, `frontend/`) must not import from `deploy/`,
    read a `fly.toml`, or branch on deployment topology — no
    "am I the cron container?" / "am I on Fly?" conditionals. If the app
    needs to behave differently, it reads a `PENNY_*` env var that deploy
    sets; the app never names the deployable.
  - `deploy/` may reference app paths (it copies and invokes them) but must
    not be imported by app code.
- This mirrors the existing **Website → Agent** one-directional rule in
  `AGENTS.local.md`. Add a new clause there:
  **"Deploy → App (one-directional). The `deploy/` domain may copy from and
  invoke `backend/`/`frontend/` and supply their env; application code must
  never import `deploy/`, read deploy config (`fly.toml`/`schedules.json`),
  or branch on deployment topology. The only runtime seam is the `PENNY_*`
  env contract (`backend/penny/config.py` + `.env.example`)."**

## Per-deployable migration

### 1. Backend service (`deploy/backend/`)

**`Dockerfile`** — port `main`'s multistage `uv` build with these deltas:
- Base `python:3.13-slim` (branch requires `>=3.13`, not 3.12).
- Builder installs `git` (for `promptorium-python` git dep) and
  `pip install uv`.
- Copy `backend/pyproject.toml backend/uv.lock`, then
  `uv sync --frozen --no-dev` (stagehand is a top-level dep now, no extra
  needed — confirm whether the deployed service needs the Amazon scraper at
  all; if not, consider gating stagehand behind an extra to shrink the
  image and drop the heavy Browserbase tree).
- Copy application source: `backend/penny`, `backend/.prompts`,
  `backend/.agent`, `backend/configs`, `backend/alembic`,
  `backend/alembic.ini`. (Mirror `main`'s prompts/configs copy; add
  `.agent/skills` which the harness discovers, and alembic since the branch
  ships it.)
- Production stage installs `libpq5` (psycopg2 runtime), copies the venv +
  source, `ENV PATH=/app/.venv/bin`.
- **Entrypoint changes from a one-shot CLI to a server:**
  `CMD ["uvicorn", "penny.api.main:app", "--host", "0.0.0.0", "--port",
  "8080"]`. Schema bootstrap already runs on FastAPI startup.

**`fly.toml`** — `app = "penny"` (or keep `transactoid`; decide naming),
`primary_region = "iad"`, `[build] dockerfile` pointed at the deploy path.
**This is now an HTTP service**, so add an `[http_service]` block
(`internal_port = 8080`, `force_https = true`, autostart/autostop as
desired) — a structural change from `main`'s no-service job. `[env]` carries
the **non-secret** `PENNY_*` runtime values sourced from
`deploy/env/deploy.env.template`; secrets (`GOOGLE_API_KEY`, Plaid, R2,
Resend, `DATABASE_URL`) go via `fly secrets set`, never in `fly.toml`.
Keep `1024mb` VM (the agent loop + matplotlib are not light).

**Build context / env contract:** context = repo root,
`--dockerfile deploy/backend/fly.toml`'s referenced Dockerfile; env contract
= the `PENNY_*` vars in `config.py`. **Resolve the editable `agent-harness`
source** before the container build (see dependency-resolvability below).

### 2. Frontend (`deploy/frontend/`)

`frontend/` is a static build. Two viable shapes — the plan recommends
**(a)** for fidelity to the current single-origin model:

(a) **Co-served / proxied static**: `npm ci && npm run build` →
`frontend/dist`, served by a tiny static server (or by the backend if we
add a static mount). The browser hits one origin and `/api` is the backend.
Requires the Vite build to run with `AGENT_UI_USE_VENDOR=1` so it consumes
the vendored `@adambossy/agent-ui` tarball (the source alias points at a
`~/code/agent-ui` path that does not exist in CI/containers — see
vite.config.ts `dedupe`/alias note; **do not** remove `resolve.dedupe`).

(b) **Separate static Fly app** (`penny-frontend`): a Dockerfile that runs
the Vite build then serves `dist/` via nginx/caddy, with the API origin
injected at build time (`VITE_…`/`BACKEND_URL`) or via a runtime proxy.

**`Dockerfile`** — node build stage (`node:22-alpine`, `npm ci`, `npm run
build` with `AGENT_UI_USE_VENDOR=1`) → static-serve stage. Copy from
`../frontend`. **`fly.toml`** — `app = "penny-frontend"`, an
`[http_service]` on the static port. **Build context** = repo root (or
`frontend/` subtree). **Env contract**: the only build input is the API
origin; document it in `deploy/env/deploy.env.template` as a `VITE_*` /
`BACKEND_URL` value.

### 3. Cron-manager (`deploy/cron-manager/`)

Port `main`'s structure directly:
- **`Dockerfile`**: `FROM registry.fly.io/<cron-manager>:<digest>` + `COPY
  deploy/cron-manager/schedules.json /usr/local/share/schedules.json`.
- **`fly.toml`**: `app = "penny-cron-manager"`, `/data` mount, `256mb`.
- **`schedules.json`**: cron entries. The image is rendered in by
  `sync_cron_manager.sh` from `fly releases` (keep that logic verbatim — it
  correctly avoids the stale-ephemeral-image trap). The **`config.env`
  block is no longer hand-maintained**; it is generated (see next section).
- **Command**: must invoke a real headless entry point. Today the branch
  has none. The design — a Typer CLI (`penny run-scheduled-report`,
  `penny run`, `penny sync`) — is specified in its own section below
  ("Headless entry point"). The cron-manager (a deploy-domain artifact)
  invokes that CLI as the container command, exactly as `main`'s
  `schedules.json` invoked `/app/.venv/bin/transactoid run-scheduled-report`.

**Build context** = repo root; **env contract** = the generated
`config.env`, which is the cron deployable's slice of the same
`PENNY_*` template.

## Headless entry point

The cron-manager's command must call something that runs the scheduled
operations **without** a browser, a chat UI, or a live HTTP request. On
`main` that something was the `transactoid` CLI; the rebuild has none. This
section designs its replacement and pins down where it sits relative to the
segregation rules — because a CLI that constructs and drives the agent is
exactly the kind of thing those rules govern.

### What the old cron actually invoked

`main`'s `schedules.json` runs two commands (verified against
`main:ops/cron-manager/schedules.json` and `main:src/transactoid/ui/cli.py`):

- `transactoid run-scheduled-report` — daily 10:00 UTC. Picks the prompt key
  by New-York-time precedence (`annual > monthly > weekly > daily`, via
  `services/scheduled_reports.select_prompt_key`), then runs the agent on
  that report prompt with `--email`/R2 output and `max_turns`.
- `transactoid run --prompt-key report-weekly-jenny --email …` — weekly
  Saturday. A plain "run the agent on this prompt key, email the result"
  invocation.

Both ultimately call one async core (`_agent_run_impl` on `main`):
construct the agent + taxonomy, `await` a single agent run on a report
prompt, then route the output (R2 upload + email). On this branch the same
shape already exists, just split differently: the **agent** drives the
report by invoking the `spending-report` skill and the delivery tools
(`penny/tools/delivery.py` → R2 + `penny/services/email.py`). So a headless
run does not need to re-implement report logic — it only needs to
**construct the agent and drive it with the right prompt**, exactly as the
web bridge does, minus the SSE translation.

### Design: a Typer CLI (`backend/penny/cli.py`)

Per the project convention in `AGENTS.local.md` ("new CLI entry points and
any CLI refactors must use Typer"), the entry point is a Typer app at
`backend/penny/cli.py`, exposed via `[project.scripts]` in
`backend/pyproject.toml` (there is **none today**):

```toml
[project.scripts]
penny = "penny.cli:main"
```

Commands (mirroring the two `main` cron invocations, plus sync):

- `penny run-scheduled-report [--email <addr> ...] [--max-turns N]`
  Picks the prompt key with the same NY-time precedence rule (port
  `select_prompt_key`), then drives the agent on that prompt headlessly.
  This is the daily-cron command.
- `penny run --prompt-key <key> [--email <addr> ...] [--max-turns N]`
  (and/or `--prompt "<text>"` for an ad-hoc run). Drives the agent on an
  explicit report prompt key. This is the weekly-cron command
  (`--prompt-key report-weekly-jenny --email …`).
- `penny sync [--count N]` — runs the Plaid sync + categorize flow headless,
  for any schedule that wants a fresh pull before reporting (wraps the same
  `penny/tools/_services/sync_service.py` the `sync` tool calls). Include it
  so a future "sync then report" schedule has a command; the old cron only
  ran reports, so this is the one net-new operation.

**How it drives the agent (no HTTP).** Each command:

1. `load_dotenv(override=False)` once at the Typer entrypoint (project
   convention), so `PENNY_*` + provider/DB secrets supplied by deploy are in
   `os.environ`.
2. `bootstrap()` (idempotent schema create + taxonomy seed) — the same call
   `api/main.py` makes on FastAPI startup, since cron runs against the same
   DB and must not assume the web service booted first.
3. Build the agent via `agent_factory.build_agent(model=build_model(),
   session=InMemorySession(...), persist_session=False)` — the **identical**
   construction path the web bridge uses, so cron and chat run the same
   tools, skills, system prompt, and model.
4. `asyncio.run(agent.run(prompt=<report-or-sync prompt>))` — drive it
   directly. No `event_bus`/SSE bridge is needed; the report's side effects
   (R2 upload, email send) happen inside the agent's tool calls, exactly as
   in an interactive run. The CLI's only post-run job is exit-code mapping
   (non-zero on failure, like `main`'s `_agent_run_impl`).

The CLI reuses `services/scheduled_reports.select_prompt_key` (port it onto
the branch) and the existing report prompt keys (`report-weekly-jenny` is
already present in `.prompts/`; add `report-daily`/`report-weekly`/
`report-monthly`/`report-annual` as the precedence rule references them, or
trim the precedence rule to the keys that exist — an implementation
decision, not a deploy concern).

### Where this sits in the segregation model

The CLI is a **third front door** into the application, alongside
`backend/penny/api/main.py` (the web/HTTP entrypoint). It is *app code*, not
*deploy code*, and not *agent-internal*:

- **It is an app entrypoint, not deploy infra.** It lives under `backend/`
  (`penny/cli.py`), is pure Python, has no `fly.toml`/Dockerfile awareness,
  and is independently runnable on a dev laptop (`uv run penny
  run-scheduled-report`). It must **not** move into `deploy/` — deploy only
  *invokes* it (via the cron container command), the same way it *invokes*
  `uvicorn penny.api.main:app` for the backend service.
- **It is allowed to construct and drive the agent** — that is precisely
  what a front door does. `api/main.py`'s bridge already constructs the
  agent via `agent_factory` and calls `agent.run(...)`; the CLI does the
  same. So the CLI may import `agent_factory`, `bootstrap`, the services,
  and the sandbox — the app-internal surface — without violating anything.
- **It is NOT agent-internal.** It does **not** live under `penny/tools` or
  `.agent/skills`, and the agent never calls it. Tools/skills are things the
  agent invokes; the CLI is a thing that invokes the agent. Keeping it out
  of `tools/`/`skills/` preserves the existing inbound boundary (front doors
  drive the agent; the agent never drives a front door).
- **Deploy → CLI is one-directional, like Deploy → App.** The cron-manager
  (deploy domain) names the CLI in its container command
  (`penny run-scheduled-report`); the CLI never names a deployable, reads a
  `fly.toml`, or branches on "am I in cron?". The only runtime seam is still
  the `PENNY_*` env contract — deploy supplies `PENNY_AGENT_*`,
  `PENNY_WORKSPACE`, `DATABASE_URL`, provider/R2/Resend secrets via the
  generated `config.env`; the CLI reads them through `config.py`/`os.environ`
  exactly as the web service does. This adds **no new seam**: it is the same
  env contract the backend deployable already depends on.

So the dependency picture stays clean: `deploy/cron-manager` → (container
command) → `penny.cli` → (constructs) → agent. One direction, no new
coupling, and `penny.cli` sits beside `penny.api.main` as a peer entrypoint.

### CLI vs. an authenticated trigger endpoint — recommendation

**Recommend the Typer CLI.** The alternative is to expose an authenticated
HTTP endpoint (e.g. `POST /api/internal/run-scheduled-report`) and have the
cron command `curl` it. Weighing them:

- **CLI (recommended).** Matches the `main` cron pattern verbatim (cron runs
  a binary in its own ephemeral machine, no live service needed). Keeps the
  cron-manager a **thin scheduler**: it boots a container, runs one command,
  exits — `auto_destroy: true`, `restart.policy: "no"`, exactly as
  `schedules.json` already specifies. No dependency on the backend web app
  being up, scaled-from-zero, or reachable; no auth surface to build or
  protect; failures surface as a non-zero exit the cron-manager already
  understands. The cost is that the cron image must carry the full app +
  deps (it already did on `main`).
- **Trigger endpoint (not recommended now).** Would let cron be a pure
  `curl` with a tiny image, but it (a) couples report runs to the web
  service's availability and scaling policy, (b) needs a new authenticated
  internal route + secret, contradicting the single-user "no auth" stance in
  `AGENTS.md`, and (c) makes a long (up to 7200s) report run a long-lived
  HTTP request behind Fly's proxy — fragile. It earns its keep only once the
  app is multi-tenant and the web service is always-on; that is a
  productionization concern, not this port.

Net: the CLI is the lower-risk, history-faithful choice and keeps the
cron-manager exactly as thin as it is on `main`. Revisit the endpoint when
the productionization plan turns the backend always-on and authenticated.

## CI workflow rework (thin shim)

Add `.github/workflows/deploy.yml` (must stay at repo root — GitHub
requirement). It is a **trigger + environment shim only**:
- Triggers: push to the release branch, the daily pre-report cron, and
  `workflow_dispatch` (port from `main`).
- Steps: checkout; set up `flyctl`; alias `fly`→`flyctl`; install the
  workspace deploy SSH key; export `FLY_API_TOKEN`; then **call
  `deploy/scripts/*.sh`** — e.g. `deploy/scripts/deploy_backend.sh`,
  `deploy/scripts/deploy_frontend.sh`, `deploy/scripts/sync_cron_manager.sh`.
- **No `fly deploy`, no `jq` rendering, no image resolution inline** — all
  of that lives in `deploy/scripts/`. The workflow body should read like a
  list of script invocations. (Drop the repo-root `Makefile` fly targets,
  or keep a thin `make` that just calls the same scripts — the scripts are
  the source of truth.)
- `FLY_API_TOKEN` must be a token (or org token) authorized for **all
  deployable Fly apps** (backend, frontend, cron-manager). Document this
  requirement next to the workflow and in `deploy/README.md`.

## Cron config single-source-of-truth fix

**Problem on `main`:** model/provider config is duplicated — `fly.toml`'s
`[env]` *and* every entry's `config.env` in `schedules.json` carry
`TRANSACTOID_AGENT_PROVIDER/MODEL` + `TRANSACTOID_CATEGORIZER_MODEL`. They
must be hand-synced or cron silently runs a different model than the web app.

**Fix:** make `deploy/env/deploy.env.template` the single source of the
shared `PENNY_*` runtime values. Then:
- `deploy/scripts/render_cron_env.sh` reads the template and emits the
  `config.env` object that `sync_cron_manager.sh` injects into each
  `schedules.json` entry (extend the existing `jq` render that already
  injects `config.image` + `config.mounts[].volume`). The committed
  `schedules.json` keeps only **schedule-specific** fields (name, cron,
  command, timeout, guest sizing, mount path) — **no model/provider env**.
- The backend `fly.toml` `[env]` is likewise generated/checked against the
  same template (a `verify-env` step can diff `fly.toml [env]` vs template
  to fail CI on drift).
- Net: one place defines provider/model; backend and cron can never
  disagree.

## Dependency-resolvability fixes for remote builds

1. **`agent-harness` editable local path must not reach the container.**
   `[tool.uv.sources] agent-harness = { path = "/Users/adambossy/code/
   agent-harness", editable = true }` will not resolve in a remote builder.
   `agent-harness` now has a pushed `main`, and the `[project.dependencies]`
   entry already names the git URL. Make the deployed build use the git ref:
   - Preferred: gate the `[tool.uv.sources]` override behind an env so the
     container build opts into git. The repo already documents an
     `AGENT_HARNESS_USE_GIT=1` intent in the pyproject comment — wire the
     Dockerfile to produce a lock/resolution without the local source
     (e.g. build with the source-replace removed, or maintain a
     deploy-time `uv.lock` resolved against the git ref). Pin to a specific
     commit/tag for reproducibility, not a moving `@main`.
   - Ensure `backend/uv.lock` committed for the deploy build reflects the
     **git** source, not the local path, so `uv sync --frozen` succeeds.
2. **`promptorium-python @ git+…@main`** resolves only if the builder has
   `git` installed (it does, per the ported builder stage) — and should be
   **pinned to a commit** rather than `@main` for reproducible builds.
3. **`.dockerignore` per image** must exclude `**/node_modules`, `**/.venv`,
   `**/__pycache__`, `*.db` (the gitignored `backend/penny.db`),
   `.worktrees`, `.git` bloat, and the `smartplan-*/` working dir, so the
   build context stays small and no local SQLite/secret leaks into an image.

## What stays OUT of `deploy/` (dev-tooling, not deploy)

These are developer/local concerns and must **not** be swept into `deploy/`:
- `.pre-commit-config.yaml` (if present), `backend/ruff.toml`, any
  mypy config — lint/format/type gates run locally and in a *test* CI job,
  not in the release pipeline.
- `.mcp.json`, `.claude/`, `.agent/` discovery roots — editor/agent dev
  config and the agent's own skills tree (the latter is application data the
  Dockerfile *copies*, but its authoring home stays in `backend/`).
- `.env`, `.env.test`, `.env.example` — `.env.example` is the app-side
  config mirror and stays in `backend/`; the deploy-side canonical template
  is the separate `deploy/env/deploy.env.template`. Real `.env*` stay
  gitignored and never enter `deploy/` or an image.
- `frontend/vite.config.ts`, `tsconfig.json` — build configuration owned by
  the app; the deploy Dockerfile merely invokes `npm run build`.

The litmus test: if removing the file would break a *developer's local
loop* but not a *production release*, it is dev-tooling and stays put.

## Risks / open questions

1. **No headless entry point on the branch (now designed).** The
   cron-manager's whole purpose is running `transactoid sync` /
   `run-scheduled-report`, which don't exist in the rebuild. This is now
   resolved by the **Headless entry point** section: a Typer CLI
   (`backend/penny/cli.py`, recommended over a trigger endpoint) is its own
   independent track (Track B) and a **prerequisite** for the cron-manager
   deployable (Convergence). The backend/frontend deployables (Track A) do
   not depend on it and can land first/in parallel.
2. **Backend is now a persistent service, not a job.** `fly.toml` needs an
   `[http_service]`, health checks, and an autostop policy decision (always
   on vs. scale-to-zero). Cost/latency trade-off to confirm.
3. **`agent-harness` git pin vs. local-path dev ergonomics.** The deploy
   build must use the git ref while local dev keeps the editable path.
   Splitting these cleanly (env-gated `[tool.uv.sources]` + a deploy lock)
   needs care so `uv sync --frozen` is reproducible in CI.
4. **Plaid Link localhost flow can't run remotely.** `connect_new_account`
   spins up a localhost HTTPS server + opens a browser; it only works on the
   user's machine (per AGENTS.md gotcha). The deployed backend must not
   expose that path as if it works remotely — orthogonal to this plan but
   worth a guard.
5. **Fly app naming** (`transactoid` vs `penny`) and **secret carryover**
   (existing `FLY_API_TOKEN` scope, R2/Plaid/Resend secrets, the
   `transactoid_workspace` volume) — decide whether to reuse the existing
   Fly apps/volume or stand up new ones.
6. **Frontend serving model** (co-served vs separate Fly app) is an open
   choice; (a) preserves the single-origin `/api` proxy assumption.
7. **Python 3.13 base image + native wheels** (`psycopg2-binary`,
   `matplotlib`, stagehand/Browserbase) — confirm all resolve on
   `python:3.13-slim`; may need extra apt build deps in the builder.

## Transition strategy (owner decisions)

This port lands while the rebuild is still being polished, so the deploy
story spans two lineages for a while. The owner has decided:

- **Deploys for the new version may be down during the supersede.** It is
  acceptable that the *rebuilt* backend/frontend/cron are not continuously
  deployable while this plan's tracks land and stabilize. We are not racing
  a zero-downtime cutover here.
- **The old `main` cron keeps running, untouched.** The existing
  `transactoid-cron-manager` Fly app continues to run off the legacy/archived
  branch (the pinned `registry.fly.io/transactoid:deployment-…` image its
  `schedules.json` already references) — **no teardown** — so scheduled
  reports keep landing in the user's inbox while the new cron-manager
  (Convergence, below) is finished. We stand up the *new* cron-manager
  beside it and only retire the old app once the new one is verified.
- **Preserve `main`'s history via a history-preserving supersede.** When the
  rebuild is ready to become `main`, archive the current `main` to a
  `legacy/<date>-transactoid` branch **and** an annotated tag, then merge the
  rebuild into `main` with a **no-force `-s ours`** merge so both lineages
  stay reachable. Do **not** force-reset `main`. (Full runbook is out of
  scope for this plan — this note only frames why the tracks below can land
  independently and why the cron-manager convergence is not on the critical
  path for keeping reports flowing.)

## Commit sequence — parallel tracks

The work fans out into **two independent tracks plus a convergence point**,
so a multi-agent execution can run Tracks A and B concurrently. Each commit
leaves the repo working; deploy artifacts are inert until the CI shim
references them, so they land incrementally within a track.

**Track A and Track B share no files and have no ordering dependency** —
Track A is `deploy/` + CI scaffolding only; Track B is pure app code under
`backend/`. The cron-manager deployable is the single **Convergence** point:
it needs Track A's `deploy/` scaffolding *and* Track B's CLI (the command it
invokes), so it lands only after both.

### Prelude (lands first, blocks nothing)

- **P1 — `docs: add deploy → app segregation clause`** — extend
  `AGENTS.local.md` with the Deploy→App one-directional rule (and the
  CLI-is-a-front-door clarification: the Typer CLI is an app entrypoint that
  may drive the agent, never agent-internal). *Track: shared prelude.
  Depends on: nothing.* (This plan doc commit is separate and already
  landed.)

### Track A — `deploy/` scaffolding + backend & frontend deployables

*Pure `deploy/` + repo-root CI. Touches no `backend/`/`frontend/` app code
except the `agent-harness` source-resolution fix in `pyproject.toml`/lock.
Runs fully in parallel with Track B.*

- **A1 — `chore(deploy): scaffold deploy/ domain + env template`** — create
  `deploy/{backend,frontend,cron-manager,scripts,env}/`, add
  `deploy/env/deploy.env.template` (single source of truth) and
  `deploy/README.md` (the seam doc). No behavior yet.
  *Depends on: P1 (clause), else nothing.*
- **A2 — `build(deploy): backend Dockerfile + fly.toml`** — port + adapt the
  multistage build for the FastAPI service (3.13 base, uvicorn entrypoint,
  HTTP service), plus `deploy/backend/.dockerignore`. Include the
  `agent-harness` git-source resolution for the container build (the only
  app-tree touch: `pyproject.toml`/lock).
  *Depends on: A1.*
- **A3 — `build(deploy): frontend Dockerfile + fly.toml`** — Vite build
  (`AGENT_UI_USE_VENDOR=1`) → static serve; `.dockerignore`.
  *Depends on: A1 (parallel with A2).*
- **A4 — `chore(deploy): port + adapt deploy scripts`** — `deploy_backend.sh`,
  `deploy_frontend.sh`, `render_cron_env.sh` (NEW, generates `config.env`
  from the template), `seed_workspace_volume.sh`. (`sync_cron_manager.sh`
  lands at Convergence with the cron deployable.)
  *Depends on: A1; A2/A3 for the scripts they invoke.*
- **A5 — `ci: thin deploy workflow shim`** — `.github/workflows/deploy.yml`
  that only sets up the environment and calls `deploy/scripts/*.sh` (backend
  + frontend; the cron-manager step is wired at Convergence).
  *Depends on: A4.*

### Track B — headless Typer CLI entry point

*Pure app code under `backend/`. Touches no `deploy/` file. Runs fully in
parallel with Track A and is independently testable (`uv run penny
run-scheduled-report` against the test DB).*

- **B1 — `feat(cli): port scheduled-report selection`** — port
  `services/scheduled_reports.select_prompt_key` (NY-time precedence) onto
  the branch and reconcile the report prompt keys it references with what
  exists in `.prompts/`.
  *Depends on: nothing.*
- **B2 — `feat(cli): headless Typer entrypoint`** — add
  `backend/penny/cli.py` (`run-scheduled-report`, `run`, `sync`) wired via
  `[project.scripts] penny = "penny.cli:main"`. Each command
  `load_dotenv` → `bootstrap()` → `build_agent(persist_session=False)` →
  `asyncio.run(agent.run(...))`, with exit-code mapping. Reuses
  `agent_factory`, the services, and `sync_service`.
  *Depends on: B1.*
- **B3 — `test(cli): scheduled-report selection + entrypoint smoke`** — unit
  test `select_prompt_key` precedence and a smoke test that the CLI
  constructs the agent and drives a stubbed run (no live model/email).
  *Depends on: B2.*

### Convergence — cron-manager deployable

*Depends on BOTH Track A (the `deploy/` scaffolding + scripts) AND Track B
(the `penny` CLI its container command invokes).*

- **C1 — `build(deploy): cron-manager Dockerfile + fly.toml + schedules.json`**
  — port the cron-manager app; `schedules.json` carries only
  schedule-specific fields (no model env) and a command of
  `penny run-scheduled-report` / `penny run --prompt-key … --email …`.
  *Depends on: A2 (the app image the cron pins), B2 (the CLI command).*
- **C2 — `chore(deploy): sync_cron_manager.sh + CI cron step`** — add
  `sync_cron_manager.sh` (image/volume render retained from `main`) and wire
  the cron step into `deploy.yml`.
  *Depends on: C1, A4, A5.*

### Follow-up (after either track)

- **F1 — `test: guardrail for deploy↔app boundary`** — assert no module
  under `backend/` or `frontend/` imports `deploy/` or reads a `fly.toml`,
  and that `penny/cli.py` is not imported by anything under `penny/tools` or
  `.agent/skills` (the CLI-is-a-front-door, not agent-internal, invariant),
  mirroring the existing website↔agent guardrail test.
  *Depends on: A1 + B2 existing.*

Critical path to "new cron-manager deployable exists": P1 → (A1→A2) ‖
(B1→B2) → C1 → C2. Backend and frontend deployables (A2/A3) can ship the
moment Track A reaches them, independent of Track B.

### Why same-repo, not a separate package

The harness and agent-ui were *extracted* into standalone packages because
they are **reusable, product-agnostic libraries** with their own release
cadence. Deploy config is the **opposite**: it is app-specific glue —
Dockerfiles that copy *this* app's source, a `schedules.json` naming *this*
app's cron commands, a CI workflow wired to *these* Fly apps. It has no life
outside this repo, must version-lock to the app source it copies, and gains
nothing from package boundaries. So `deploy/` is a **top-level directory in
the same repo**, segregated by directory and dependency direction — not a
separate package.
