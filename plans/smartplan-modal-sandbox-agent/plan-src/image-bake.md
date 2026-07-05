---
id: image-bake
label: Image bake & cold start
parent: packaging
sections: [base-image, snapshot-strategy, cold-start-budget]
crosslinks: [packaging, turn-lifecycle]
---

# Image bake and cold start

One stable base image, per-conversation workspace deltas mounted on top, and a runner kept deliberately import-light. Cold start is a budget with a number, not a hope.

## Requirements

- The first message to a cold conversation reaches first token within a few seconds; a restored conversation is not meaningfully slower than a fresh one.
- Upgrading the runner or its dependencies never invalidates existing conversation workspaces.
- Building and publishing a new sandbox image is one command in the deploy domain.

## base-image — The base image

Defined in `deploy/sandbox/modal_app.py` with Modal's image builder (layer-cached per method call), ordered most-stable-first so day-to-day runner edits rebuild only the last layers:

- `Image.debian_slim(python)` plus `apt_install` (git, ripgrep — what skills need).
- `uv_sync()` from `sandbox/pyproject.toml`'s lockfile — agent-harness[mcp], the model SDK, fastapi/uvicorn, pydantic. **No finance stack**: the MCP split keeps SQLAlchemy, Plaid, boto3, psycopg out (enforced by the denylist gate on the Packaging page).
- Skills tree copied in (`backend/.agent/skills` to `/opt/agent/skills`, `copy=True` — baked layers, required for images used as sandbox bases).
- Runner source copied in (`copy=True`), `entrypoint` equals the runner server on the tunnel port. Entrypoint-as-server is deliberate: Modal exec streams can't be re-attached; the tunnel-exposed server can.
- Pre-built and published by `modal deploy`; the resulting image is referenced by the backend via a `PENNY_SANDBOX_IMAGE`-style env value (deploy supplies it; app code never names a deploy artifact). A Dockerfile variant (`Image.from_dockerfile`) is the documented escape hatch if the image ever needs to build outside Modal's builder.

## snapshot-strategy — Snapshot strategy: stable base plus workspace delta

Per-conversation state is only ever `/workspace`. At reap, `sb.snapshot_directory('/workspace')` produces a small delta image (Modal stores only modified files); on restore, a fresh sandbox boots from the *current* base image and the delta is attached via `mount_image('/workspace', snapshot)`. Consequences:

- **Base upgrades are free**: conversations restored tomorrow get tomorrow's runner plus deps with yesterday's workspace — no migration of full-filesystem snapshots.
- **One snapshot per conversation**: the new image id replaces the old on the conversation record; the superseded image is deleted (`image_delete`). Expired (30-day TTL) or missing snapshots degrade to a cold start with an empty workspace — an accepted, defined behavior, not an error. Modal does not currently charge for snapshot image storage, so one delta per conversation carries no storage cost today.
- **Fallback if directory-mount misbehaves** (it is newer API surface): full `snapshot_filesystem()` used as the boot image is the boring, fully documented alternative — same lifecycle, bigger images, base upgrades require a re-snapshot cycle. The lifecycle module isolates this choice behind one interface so switching is contained.

## cold-start-budget — Cold-start budget

Target: **3 s or less from `Sandbox.create` to runner-ready** (readiness probe on the tunnel port), measured as a delivery gate. The levers, in order of impact:

- **Import weight is the enemy**, and the MCP split already removed most of it. The runner's import set is harness plus mcp plus one model SDK plus fastapi. A CI check times `python -c "import runner.server"` and fails over budget (say 1.5 s) so import creep is caught at review time.
- **Modal's lazy content-addressed filesystem** pulls only what the process touches — another reason a small import set matters more than image size on disk.
- **Readiness probe** (`Probe.with_tcp(port)`) lets Fly block precisely until serving, instead of polling with sleeps.
- **What we are not doing yet**: Modal memory snapshots for sandboxes would resume a pre-imported process (their Function analog claims 3 to 10 times faster cold starts) but are alpha, terminate-on-snapshot, and expire in 7 days non-renewably. Revisit at GA; the runner's disk-rehydration design means adopting them later is additive.
- First-token latency also rides the turn payload (system prompt rendered on Fly — no schema/taxonomy queries from the sandbox) and the proxy hop (one extra TLS connection; the proxy Function kept warm with a small `min_containers` if measurement demands it).
