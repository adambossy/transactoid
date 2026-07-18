# penny-eval — isolated categorizer-eval app

The daily categorizer eval (`penny eval-categorizer`) runs here, **not** in the
`penny` app. Rationale: the eval replays the agent over untrusted merchant
descriptors, so it lives in its own Fly app with a **reduced secret set** — a
compromise can't reach the web app's Plaid/Clerk/Modal credentials. It reuses
the backend **image** (one build, two apps): `deploy/scripts/deploy_eval.sh`
deploys `penny`'s latest image ref to `penny-eval`.

The cron-manager targets it via the `penny-eval-categorizer-12h` entry in
`deploy/cron-manager/schedules.json` (`app_name = "penny-eval"`), spawning an
ephemeral, auto-destroyed machine per run. No machine runs steady-state.

## Secrets (set once on the app)

Only what the eval needs — deliberately **no** `PLAID_*`, `CLERK_*`, `MODAL_*`,
`BROWSERBASE_*`, `PENNY_PLAID_TOKEN_KEY`:

```bash
fly secrets set -a penny-eval \
  DATABASE_URL='...' \                      # eval-store writes (owner role)
  PENNY_AGENT_READONLY_DATABASE_URL='...' \ # finance reads (SELECT-only role)
  GOOGLE_API_KEY='...' \                     # gemini categorizer
  R2_ACCOUNT_ID='...' R2_ACCESS_KEY_ID='...' R2_SECRET_ACCESS_KEY='...' R2_BUCKET='...' \
  RESEND_API_KEY='...' \                     # status/heartbeat email (or SMTP_*)
  PENNY_CRON_HOUSEHOLD_ID='...' \            # RLS principal for the read-only snapshot
  PENNY_CRON_USER_IDS='...'                  # comma-separated household user ids
  # Optional: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST / PENNY_LANGFUSE_ENABLED
```

`FLY_API_TOKEN` used by CI must be authorized for `penny-eval` too.

`PENNY_AGENT_READONLY_DATABASE_URL` must point at the `penny_agent_ro` role, which
needs `EXECUTE` on the `penny_set_tenant` wrapper (see `backend/.env.example` role
setup) — the RLS-scoped snapshot pins the tenant through it, so a missing grant
makes every run fail on the first `SELECT`.

## Workspace volume

The categorizer reads `merchant-rules.md` from `PENNY_WORKSPACE`. Create + seed a
dedicated volume (same source repo as `penny`, so rules match at deploy time):

```bash
APP_NAME=penny-eval \
WORKSPACE_VOLUME_NAME=penny_eval_workspace \
  ./deploy/scripts/seed_workspace_volume.sh
```

(`sync_cron_manager.sh` creates the volume if missing and resolves its id per
app.) Known limitation: runtime rule edits on `penny`'s volume can drift from
this copy — follow-up may source rules from a shared location.

## First-run watermark (do once at cutover)

The eval watermark is NULL, so the first unbounded run would replay the entire
transaction history in one job and blow the 2h timeout. Seed a completed
watermark row so the first scheduled run only evaluates transactions going
forward (skipping the historical backlog):

```sql
-- Start the daily eval "now": subsequent runs pick up everything ingested after.
-- household_id MUST match PENNY_CRON_HOUSEHOLD_ID — the watermark is resolved per
-- household, so a row with a NULL/other household would not gate this cohort.
INSERT INTO eval_runs (run_at, status, cohort_size, cohort_max_created_at, household_id)
VALUES (now(), 'completed', 0, now(), '<PENNY_CRON_HOUSEHOLD_ID>');
```

`--limit N` is a non-committing smoke test (most-recent N, watermark NOT
advanced) — safe to run against prod without perturbing the daily cohort:

```bash
fly machine run <penny image> -a penny-eval --rm --entrypoint /bin/sh \
  -- -lc '/app/.venv/bin/penny eval-categorizer --limit 20 --email adambossy@gmail.com'
```
