# Modal sandbox integration — implementation log

A running record of obstacles, direction changes, and new decisions made while
implementing the plan under `plans/smartplan-modal-sandbox-agent/`. Newest
entries appended per phase.

## Phase 1 — protocol + runner (DONE, verified: 12/12 tests)

- **Decision — codec is structural, not schema-per-field.** Harness events are
  frozen dataclasses with pydantic payloads and no JSON round-trip. Rather than
  hand-maintain a field-type map per event, the codec wraps pydantic/type/
  ToolResult values with self-describing markers (`__pyd__`/`__type__`/`__tr__`)
  and reconstructs structurally on decode. One registry of the ~8 pydantic
  payload classes + the event-class-by-name map is all it needs.
- **Decision — `RunEnd.result` dropped on the wire.** It is a Layer-3
  `RunResult`, never consumed by the UI translation; the relay rebuilds parts
  from streamed events. Encoded as `None`. `Error.cause` (an exception *type*)
  encodes by qualified name.
- **Decision — runner is one-active-run, retains the last run for replay.**
  First cut cleared finished runs from state, which would 404 a resume GET after
  the turn ended. Fixed: a `runs` dict retains the current/last run so the log
  stays replayable within the grace window; `active` is only the in-flight one.
- **Obstacle — cancel could interrupt its own cleanup.** Cancelling the *drive*
  task risked killing the `finally` that flushes the terminal event. Fixed by
  cancelling only the inner `agent_task`; the bus close then ends the drain loop
  naturally, which appends the "run cancelled" Error and closes the log.
- **Decision — injectable `RunDriver`.** The server takes a driver callable so
  tests drive a scripted fake agent (no model, no MCP). The default builds the
  real agent from the payload. This is what makes Phase 1 verifiable without
  Modal or a model key.
- **Obstacle — Google provider ignores `base_url`.** Confirmed in harness
  source: `GoogleProvider` accepts `base_url` but never applies it. Workaround
  in `agent_assembly`: build the `genai` client with `http_options.base_url` and
  inject via `client=`. Anthropic/OpenAI honor `base_url` directly. Upstream
  one-line fix to file separately.
- **Note — test deps.** Ran Phase 1 tests through the backend venv (which has
  agent-harness editable) with an ephemeral `pytest-asyncio`; dropped the
  `asgi-lifespan` dependency (ASGITransport needs no lifespan for these
  endpoints) to keep the test env minimal.

## Phase 2 — MCP tool server (DONE, verified: 2/2 tests)

- **Obstacle — `mcp` not installed.** agent-harness declares `mcp` only in an
  optional extra, and penny's backend pulled `[anthropic,openai,google,otel]`
  but not `[mcp]`. Added `mcp>=1.0` to backend deps directly (got 1.28.1) so both
  this server and the runner's harness MCP client resolve it.
- **Decision — low-level `Server`, not `FastMCP`.** FastMCP derives a tool's
  JSON schema from a Python function signature; we must pass the *harness* tool
  schemas through verbatim to preserve tool identity. The low-level
  `mcp.server.lowlevel.Server` + `StreamableHTTPSessionManager(stateless=True)`
  lets `list_tools` return `types.Tool(inputSchema=tool.schema)` unchanged and
  `call_tool` return a hand-built `CallToolResult`.
- **Decision — capability registry is in-memory on main.** App-owned data belongs
  in a website store; on the single-user main baseline an in-memory
  `CapabilityRegistry` (token→`Principal`) suffices and the seam is shaped for the
  account-creation `RequestContext`. Tenancy binding is a documented stub here.
- **Decision — auth as ASGI wrapper, principal on a ContextVar.** The bearer
  capability token is checked in a thin ASGI handler wrapping the MCP transport;
  a valid token sets a `_principal` ContextVar (the tenancy seam) for the
  duration of the request; missing/invalid → 401 before the MCP app runs.
- **Obstacle — `Toolset` import path.** It lives in `agent_harness.core.toolsets`,
  not `core.tools`. Also `MCPServerHTTP` takes `name` as the first positional
  (fixed the runner's `agent_assembly` call: `MCPServerHTTP("penny-tools", url, ...)`).
- **Obstacle — denial raises at the client handshake.** The harness MCP client's
  401 surfaces during `__aenter__` (initialize), not at `list_tools`; the test
  had to wrap the whole `async with` in `pytest.raises`. Confirms unauthenticated
  clients cannot even initialize.
- **Verified:** a real `MCPServerHTTP` client (the one the runner uses) lists +
  calls a tool over a live uvicorn-served streamable-HTTP app with token auth,
  the value round-trips, and a token-less client is denied.

## Phase 3 — secrets proxy (core DONE, verified locally 3/3; Modal deploy pending)

- **Decision — split proxy into testable core + thin Modal wrapper.** `core.py`
  is pure FastAPI+httpx (`build_proxy_app`) so the security gates are unit-tested
  without Modal; `modal_app.py` only supplies the real keys (Modal Secret) and
  the upstream host. Verified locally against a fake upstream via injected
  `httpx.ASGITransport`.
- **Obstacle (real bug caught by the test) — path allowlist vs. Starlette.**
  `{path:path}` strips the leading slash, so `/v1/messages`-style allowlist
  entries never matched. Fixed by normalizing to `"/" + path.lstrip("/")` before
  the suffix check. `:generateContent` matched by luck (no leading slash);
  `/v1/messages` did not until the fix.
- **Decision — key injection shape.** The real key goes into a provider-specific
  header (`x-goog-api-key` for Gemini; `x-api-key`/Bearer for Anthropic/OpenAI),
  chosen by the binding Fly registers. The capability bearer is stripped from the
  forwarded headers; the test asserts the token never reaches upstream.
- **Known limitation — single upstream host.** The proxy pins one upstream
  (Gemini) since Penny runs Gemini. Multi-provider needs a per-binding
  `upstream_base`; the binding already carries the auth header, so this
  generalizes without touching the core. Logged, deferred.
- **Known limitation — registry durability.** `SessionRegistry` is in-memory
  (per Modal container). Prod backs it with a `modal.Dict` so a cold replica
  rehydrates bindings. Left in-memory in the deploy artifact for reviewability.
- **Verified locally:** valid token → real key injected + response forwarded;
  revoked conversation → 401; disallowed path → 404; admin needs its token.
- **Pending (needs live Modal + a real key from .env):** `modal deploy` the
  proxy, register a session, and complete a streamed Gemini call end to end.

## Phase 4 — Modal image bake + lifecycle + reaper (reaper verified 7/7; LIVE smoke PASS)

- **Verified (unit):** the reaper/dispatch state machine — running turn never
  reaped; uncontested idle reap commits + terminates; **a turn mid-snapshot
  steals the box back (epoch bump, no terminate, box reused)**; snapshot failure
  keeps the box; post-terminate turn cold-restores; second concurrent turn 409s.
- **Verified (LIVE, one build cycle after fixes):** built the Modal image
  (`deploy/sandbox/modal_app.py`), created a real Sandbox running the runner as
  its command, resolved the tunnel, and got `healthz -> 200` over it. Proves
  agent-harness + runner import and serve inside a Modal sandbox.
- **Obstacle — Python 3.13 required.** agent-harness needs `>=3.13`; the image
  was pinned to 3.12 and the pip step failed. Bumped `debian_slim(python_version=
  "3.13")`.
- **Obstacle — `wait_until_ready` needs a readiness probe.** It is keyword-only
  (`timeout=`) AND raises `ConflictError` without a configured probe. Dropped it
  in favor of polling `/healthz` through the tunnel until 200 — robust and probe-
  independent. (Runtime provider can add `Probe.with_tcp` later.)
- **Obstacle (the real one) — `pydantic-graph` version drift.** A loose pip
  resolve inside the image pulled a `pydantic-graph` that dropped
  `GraphRunResult`, crashing the runner on import (the sandbox came up but
  `/healthz` never answered). Pinned `pydantic-graph==1.103.0` + `pydantic==
  2.13.4` (the backend's known-good resolution). This is the lesson of vendoring
  a git dep without the app's lockfile — pin the transitive troublemakers.
- **Decision — install agent-harness from its pinned git commit, not the local
  editable.** The repo is public, so the image installs
  `agent-harness[mcp,google] @ git+...@<commit>` and vendors only the `sandbox/`
  source via `add_local_dir(copy=True)`. Avoids shipping the local checkout.

## Phase 5 — Fly relay + chat orchestration (relay verified 2/2)

- **Verified:** the Fly relay pulls a *real* Phase-1 runner over HTTP, decodes
  wire envelopes, translates via `bridge._translate` to AI SDK frames (text
  round-trips), and the `FrameBuffer` replays the whole turn for browser resume —
  the full wire path, Modal-independent.
- **Decision — reuse `bridge._translate` unchanged.** The relay decodes to real
  harness events and feeds the existing translator, so the browser frames are
  byte-identical to today; only the codec is new.
- **Written (not yet live-wired):** `chat.py` orchestration (dispatch → payload →
  POST /turns → relay → persist → on_turn_end; plus `cancel_turn`). Final wiring
  into `api/main.py` behind `PENNY_SANDBOX_TURNS` + the resume/cancel endpoints is
  the remaining integration.

## Phase 6 — end-to-end verification (PENDING full-stack live run)

- The four browser scenarios need the whole stack up at once: frontend + Fly
  backend (chat wired into main.py) + **ngrok** (so the Modal sandbox can reach
  Fly's MCP server) + the deployed proxy Function + real Gemini. That live
  orchestration exceeds this session; the scenario spec + steps are recorded.

## Phase 6 — full-stack live e2e (ALL FOUR SCENARIOS VERIFIED)

Stood up the real stack: frontend (vite) → backend (uvicorn, `PENNY_SANDBOX_TURNS=1`)
→ Modal sandbox runner → Gemini via the deployed secrets-proxy Function →
tools via the MCP server exposed to Modal through **ngrok**.

- **Scenario 1 (happy path)** — VERIFIED via the real browser AND API: the sandbox
  serves the turn, Gemini answers through the proxy ("verified via modal sandbox").
- **Scenario 2 (tool call)** — VERIFIED via the real browser AND API: the UI shows a
  "run_sql Completed" tool card and "The answer is 42"; `run_sql` executed on Fly
  over MCP (not in the sandbox), authed by the capability token.
- **Scenario 3 (cancel)** — VERIFIED via API: POST `/api/chat/{id}/cancel` → runner
  `/runs/{id}/cancel` → "run cancelled" terminal event → clean close, no full finish.
- **Scenario 4 (persistence)** — VERIFIED via API: 2 messages persist + rehydrate
  through `/api/sessions/{id}`.

Obstacles hit and fixed during the live bring-up (each a real integration bug):

- **Stale backend on :8000.** A pre-existing in-process backend held the port; my
  sandbox backend failed to bind (nohup swallowed the error) and the OLD one served
  the first "passing" runs via the in-process path — NOT the sandbox. Caught it via
  the missing cancel route + `openapi.json`. Killed the stale process; re-verified.
  Lesson: always confirm which process owns the port before trusting a green run.
- **Provider `wait_until_ready` needs a readiness probe.** Same fix as the smoke:
  poll `/healthz` through the tunnel (the provider still used the old call).
- **`GoogleModel` → `GeminiModel`.** The harness class is `GeminiModel`; `Agent`
  also requires `name`; and the genai `base_url` must go through `HttpOptions(...)`
  (a dict key `base_url` is ignored). Three bugs fixed in one image rebuild.
- **Proxy registry per-container → `modal.Dict`.** The in-memory `SessionRegistry`
  meant `register` and the model call landed on different proxy replicas → 401
  "invalid or revoked capability token". Backed it with a shared `modal.Dict`.
- **MCP mount lifespan.** A FastAPI-mounted sub-app's lifespan does NOT fire, so the
  MCP `StreamableHTTPSessionManager` task group never started → 500. Fixed by
  exposing `create_mcp()` and running the manager in the main app's `lifespan`.
- **Trailing slash.** `POST /mcp` 307-redirects to `/mcp/`, breaking the MCP client;
  the runner reaches `PENNY_MCP_PUBLIC_URL` = `<ngrok>/mcp/`.
