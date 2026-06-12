# deploy/ — the release & runtime domain

`deploy/` is Penny's **fifth segregated domain** (see the "Deploy vs. app"
hard constraint in `AGENTS.local.md`). Everything release- and runtime-shaped
lives here: Dockerfiles, `fly.toml`s, the cron schedule, deploy scripts, and
the env template. Application code under `backend/` and `frontend/` holds
**zero** deploy artifacts.

## The one-directional rule: Deploy → App

`deploy/` may **copy from** and **invoke** the app; the app may never reach
back.

- **Build-time** (allowed, one-directional): each `deploy/<x>/Dockerfile`
  `COPY`s from `../backend` / `../frontend`. The build context is the **repo
  root** so the build can see both `deploy/` and the app trees:

  ```sh
  fly deploy --config deploy/backend/fly.toml \
             --dockerfile deploy/backend/Dockerfile
  # (run from the repo root; the scripts in deploy/scripts/ do this for you)
  ```

  Each `deploy/<x>/.dockerignore` trims that context per image.

- **Runtime** (the only seam): the **`PENNY_*` env contract**. The app reads
  config via `backend/penny/config.py` + `os.environ`; deploy supplies values
  via fly `[env]`, `fly secrets set`, and the cron `config.env`.
  `deploy/env/deploy.env.template` is the canonical list;
  `backend/.env.example` is the app-side mirror for local dev.

- **Forbidden:** app code must not import from `deploy/`, read a
  `fly.toml`/`schedules.json`, or branch on deployment topology. If the app
  must behave differently, it reads a `PENNY_*` env var deploy sets — it never
  names a deployable. A guardrail test (`tests/test_deploy_segregation.py`)
  enforces this.

## Topology

Three Fly apps + a CI shim:

| Deployable          | Path                  | Shape                                  |
| ------------------- | --------------------- | -------------------------------------- |
| Backend             | `deploy/backend/`     | Persistent HTTP service (`uvicorn`).   |
| Frontend            | `deploy/frontend/`    | Static build, served / proxied.        |
| Cron-manager        | `deploy/cron-manager/`| Scheduler; spawns ephemeral job machines that run the `penny` CLI. |
| CI shim             | `.github/workflows/deploy.yml` | Thin: sets up flyctl, calls `deploy/scripts/*.sh`. |

The CI workflow file must stay at the repo root (GitHub requirement) but holds
no deploy logic — it only invokes `deploy/scripts/*.sh`.

## The headless job contract (Sprites-forward)

The cron-manager runs the `penny` Typer CLI (`backend/penny/cli.py`,
`[project.scripts] penny`) in an ephemeral, auto-destroyed machine built from
the **app image**, with per-job env injected from the cron `config.env`. The
CLI is *app code* (a peer front door beside `penny.api.main`), not deploy
code; deploy only names it in the container command. Migrating to Fly Sprites
later swaps only the spawn primitive — the CLI/image/env contract is unchanged.

## Cron config single-source-of-truth

`deploy/env/deploy.env.template` is the one place that defines the shared
model/provider/workspace values. `deploy/scripts/render_cron_env.sh` emits the
cron `config.env` from it; `sync_cron_manager.sh` injects that (plus the
resolved image + volume id) into `schedules.json` at deploy time. The
committed `schedules.json` therefore carries only **schedule-specific** fields
(name, cron, command, timeout, guest sizing, mount path) — no model env — so
backend and cron can never drift.

## Fly credentials / secrets (manual prerequisites)

`fly deploy` cannot run from this environment (no creds/network). To deploy:

- `FLY_API_TOKEN` must be authorized for **all** deployable apps (backend,
  frontend, cron-manager). In CI it is `secrets.FLY_API_TOKEN`.
- Set the section-2 secrets from `deploy/env/deploy.env.template` on each app
  with `fly secrets set …` (at minimum `GOOGLE_API_KEY`, `DATABASE_URL`, the
  Plaid + R2 + Resend keys).
- The cron workspace volume + its seed are handled by
  `deploy/scripts/seed_workspace_volume.sh`.
