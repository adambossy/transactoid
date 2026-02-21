# Cron Job Hardening: Recurring Failures and Fixes

**Date:** 2026-02-21
**Context:** The scheduled daily report job broke every day for ~1 week. Each morning
required manual diagnosis and repair. This file captures every root cause found, the
fix, and what to check going forward.

---

## Root Cause 1: Cron Manager Pinned to Old Image

### What broke
The `transactoid-cron-manager` app manages scheduled job runs. It reads
`/data/schedules.json` which contains a **hardcoded image tag** for each job. When
`fly deploy` updates the persistent app machines, the cron manager's config is NOT
automatically updated. Every deploy produces a new image tag; the cron manager keeps
running jobs from the old one.

This caused failures like `create_agent is only supported with OpenAI runtime` because
cron jobs were running old code while the fix was only on the newly deployed machines.

### Fix
After every `fly deploy`, manually update the cron manager's `schedules.json`:
```bash
NEW_TAG=$(fly machines list --app transactoid --json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)[0]['config']['image'])")

fly ssh console --app transactoid-cron-manager \
  --command "sed -i 's|registry.fly.io/transactoid:deployment-[A-Z0-9]*|$NEW_TAG|g' /data/schedules.json"

# Verify
fly ssh console --app transactoid-cron-manager --command "cat /data/schedules.json" | grep '"image"'
```

### Checklist item
**Every time `fly deploy` is run: update the cron manager image too.**

---

## Root Cause 2: `create_agent is only supported with OpenAI runtime`

### What broke
`AgentRunService._execute_inner` called a legacy `create_agent()` shim that only
supported OpenAI. When `TRANSACTOID_AGENT_MODEL` was set to a Gemini model, every
agent run immediately failed with this error.

### Fix (2026-02-21)
Replaced the OpenAI-only shim with `CoreRuntime` — a provider-agnostic abstraction.
Commits: `35ea7bf` through `c68e964` (branch `feature/agent-runtime-selection-parity`,
merged to main). Now `AgentRunService` uses `load_core_runtime_config_from_env()` and
works with OpenAI, Gemini, and Claude providers.

### How to detect
```
Agent run failed: create_agent is only supported with OpenAI runtime
```
In `fly logs --app transactoid`.

### Prevention
- The `CoreRuntime` abstraction is now in place — this specific error should not recur.
- If it does, check `src/transactoid/services/agent_run/service.py` for any remaining
  provider-specific forks.

---

## Root Cause 3: Gemini Categorizer — JSON Mode + GoogleSearch Incompatible

### What broke
`categorizer_tool._call_gemini_api` passed both `response_mime_type="application/json"`
AND `tools=[Tool(google_search=GoogleSearch())]` in the same Gemini API call. Gemini
forbids this combination and returns:
```
400 INVALID_ARGUMENT: Tool use with a response mime type: 'application/json' is unsupported
```

The bug was masked for weeks because the file cache served most categorization requests.
Only cache-miss batches (new transactions hitting the real API) triggered the failure.

### Fix (2026-02-21)
Removed `GoogleSearch` from the categorizer's Gemini API call. Structured JSON output
is preserved; web search grounding is dropped. Commit: `9599e14`.

### How to detect
Error appears in the **agent run failure log** (not in the categorizer's own logs),
because the exception propagates up through the agent's tool call stack:
```
ERROR | service:_execute_inner:173 - Agent run failed: 400 INVALID_ARGUMENT.
{'error': {'message': "Tool use with a response mime type: 'application/json' is unsupported"}}
```
Timing tells you it's a categorizer issue: the error fires ~200–300ms after a
`Calling gemini API for N transactions` log line.

### Prevention
- Gemini API rule: `response_mime_type` and grounding tools (`GoogleSearch`) are
  mutually exclusive. Never combine them.
- Watch for cache miss patterns: if all categorizer calls are cache hits, live API
  errors won't surface until a new merchant/date appears.

---

## Root Cause 4: Gemini Model Instability (`gemini-3-flash-preview`)

### What broke
`gemini-3-flash-preview` consistently returned `500 INTERNAL` errors on long multi-turn
sessions (e.g. weekly/monthly reports with 200+ tool calls). The failure was
deterministic at ~70s into the run.

### Fix
Switched to `gemini-2.5-flash` as the default in `src/transactoid/core/runtime/config.py`
and updated the Fly secret: `fly secrets set TRANSACTOID_AGENT_MODEL=gemini-2.5-flash`.

### Prevention
- Avoid preview models in production scheduled jobs.
- `gemini-2.5-flash` has been stable through weekly and monthly report runs (~240s).

---

## Root Cause 5: `fly machine run` Shell Expansion / Double-Shell

### What broke
When manually triggering a job with `fly machine run`, passing a command like:
```bash
fly machine run ... -- /bin/sh -lc "transactoid run-scheduled-report"
```
combined with Dockerfile `ENTRYPOINT ["/bin/sh", "-lc"]` results in double-shell
execution: `/bin/sh -lc /bin/sh -lc ...`. The inner shell treats the next argument
as the command string (e.g. `run-scheduled-report` becomes `$0`, not args).

### Fix
Use `--entrypoint` to override the entrypoint entirely:
```bash
fly machine run registry.fly.io/transactoid:deployment-XXXXX \
  --app transactoid \
  --restart no \
  --region iad \
  --vm-size shared-cpu-1x \
  --vm-memory 1024 \
  --entrypoint /app/.venv/bin/transactoid \
  -- run --prompt-key report-monthly --email adambossy@gmail.com
```

---

## Root Cause 6: `fly machine run --env` Does Not Override Secrets

### What broke
Attempting to override `TRANSACTOID_AGENT_MODEL` via `--env` in `fly machine run`:
```bash
fly machine run ... --env TRANSACTOID_AGENT_MODEL=gemini-2.0-flash-exp ...
```
Fly secrets take precedence over per-machine `--env` overrides. The `--env` flag is
silently ignored when the same variable is set as a secret.

### Fix
To change the model for all runs: `fly secrets set TRANSACTOID_AGENT_MODEL=gemini-2.5-flash`

To test a specific model for one run: temporarily override the secret, test, then restore.

---

## Standard Debugging Runbook

When the scheduled report fails, check in this order:

### 1. Check the cron manager logs
```bash
fly logs --app transactoid-cron-manager
```
Tells you which machine ID ran and whether it failed with exit code 1.

### 2. Check the transactoid app logs for that machine
```bash
fly logs --app transactoid --machine <machine-id>
```

### 3. Map error to root cause

| Error message | Root cause | Fix |
|---|---|---|
| `create_agent is only supported with OpenAI runtime` | Old image in cron manager | Update schedules.json image tag |
| `Tool use with a response mime type: 'application/json' is unsupported` | Categorizer GoogleSearch + JSON mode | Already fixed in `9599e14`; check if regression |
| `500 INTERNAL` at ~70s into run | gemini-3-flash-preview instability | Switch to `gemini-2.5-flash` |
| `429 RESOURCE_EXHAUSTED` / `CREDITS_EXHAUSTED` | Plaid free-tier investment API limit | Expected; investments sync degrades gracefully |
| `404 NOT_FOUND` for Gemini model | Deprecated model name | List available models, update `TRANSACTOID_AGENT_MODEL` |

### 4. After any `fly deploy` — always update cron manager image
```bash
NEW_TAG=$(fly machines list --app transactoid --json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)[0]['config']['image'])")

fly ssh console --app transactoid-cron-manager \
  --command "sed -i 's|registry.fly.io/transactoid:deployment-[A-Z0-9]*|$NEW_TAG|g' /data/schedules.json"
```

---

## Hardening TODO

- [ ] Automate cron manager image update as a post-deploy step (e.g. in `fly.toml`
      deploy hooks or a Makefile `deploy` target)
- [ ] Add a smoke test job that runs `transactoid --help` and verifies exit 0 before
      each scheduled run (catch image/entrypoint issues before the 2hr timeout)
- [ ] Consider switching to `fly deploy`-managed cron (no pinned images) instead of
      the cron-manager pattern, so the image tracks deployments automatically
- [ ] Add alerting on cron job failure (e.g. PagerDuty webhook or Fly health check
      notification) so failures surface before the next day's manual check
