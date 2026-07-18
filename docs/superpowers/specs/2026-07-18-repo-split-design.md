# Repo split: local-first agent core (`transactoid`) + web product (`penny-web`)

**Status:** approved design, not yet executed. No changes have been made to either repo.

## Goal

Split the current single repo into two:

- **`penny` (this repo, renamed from `transactoid`; public) — the agent
  core.** A local-first agent runnable directly by harnesses (Claude Code,
  Codex, pi.dev, …). Ships the agent essentials: tools, skills, system
  prompt, taxonomy, finance DB layer, the headless CLI, and the eval —
  surfaced to harnesses via a stdio MCP server (`penny mcp`) with a
  long-lived sync daemon (`penny daemon`) beside it. **No user-session agent
  loop**: the interactive loop is the user's harness locally, or `penny-web`'s
  loop in prod; ephemeral in-service agents (the categorizer) remain core
  implementation details, so agent-harness stays a core dependency for
  primitives (`@tool`, `Toolset`, the categorizer's ephemeral `Agent`) — not
  for a chat surface. Single-tenant by construction (end state). The
  workspace is a plain local directory the user manages (default stays
  `~/.transactoid`) — a path reference, nothing more.
- **`penny-web` (new repo; private) — the product.** Frontend, FastAPI
  backend (bridge, auth, billing, conversation persistence, households), the
  sandbox runner, the Fly/Modal deploy pipeline, and multi-tenancy layered on
  top of the agent core, which it consumes as a **pinned git dependency**
  (the same pattern this repo uses for agent-harness).

Dependency direction is unchanged from AGENTS.md: **website → agent, never
the reverse** — it just becomes a repo boundary instead of a package boundary.

## Decisions taken

| Decision | Choice |
| --- | --- |
| Boundary | Full domain split (web backend moves out, not just frontend/deploy) |
| History | Web-app history moves to `penny-web` via `git filter-repo`; this repo's history is **rewritten** to remove those paths (force-push, all hashes change) |
| Sequencing | **Prototype the tenancy inversion first (user-reviewed), then split.** The Scope-seam spike happens in the mono-repo where iteration is cheap; the split follows once the seam is validated |
| Tenancy | **Option A (Scope protocol)**, staged: a reviewed prototype first; after review, either land the full inversion pre-split (recommended if the prototype holds) or fall back to the Option C interim (tenancy duplicated in both repos, fixed local principal) |
| Sandboxes | Move to `penny-web` (Modal runner, wiring, deploy) |
| Evals | Stay in the agent core (incl. `deploy/eval/`) |
| Workspace | Hybrid R2/DB workspace store moves to `penny-web`; core keeps plain local-directory resolution (default `~/.transactoid`; rename deferred) |
| Harness surface | Core ships a stdio MCP entrypoint (`penny mcp`) exposing the toolsets verbatim; dynamic prompt blocks rendered into MCP `initialize` instructions; static identity/behavior in a checked-in agents-doc |
| Agent loop | No user-session loop in core — the harness (local) or `penny-web` (prod) owns it. `agent_factory` splits: prompt render + toolset assembly stay; `build_agent` moves to web. Loop-driving CLI commands move to a web-owned CLI |
| System prompt | Core's `penny-system-prompt` stays the single base; `penny-web` keeps *addendum* prompt keys (households, multi-user, joint sessions) in its own `.prompts/` and concatenates base + addenda |
| Daemon | Two-process topology: per-session stdio `penny mcp` + long-lived `penny daemon` (runs sync → categorizer agent), sharing state via SQLite (WAL); `sync_status` tool reads DB watermarks |
| Naming / visibility | Core repo renamed `transactoid` → `penny` (GitHub auto-redirects), **public**; web repo `penny-web`, **private**. Public core ⇒ no build credentials needed for the git dep |
| Local data | Fresh start: local SQLite DBs are disposable (rebuild via bootstrap + re-sync); workspace *files* (memory/, reports/) carry over; snapshot any non-re-derivable local DB before phase 5; no converter tooling |
| Versioning | Semver-ish `v0.x` tags on demand (the agent-harness workflow); `penny-web` bumps the pin + lock in the same PR that consumes the change; Scope/prompt contract changes get a minor bump + CHANGELOG line |

## File ledger

The path lists below drive both filter-repo operations (extraction into
`penny-web` and clearing from this repo). Paths are as they exist today.

### Moves to `penny-web`

| Area | Paths |
| --- | --- |
| Frontend | `frontend/` |
| Deploy | `deploy/backend/`, `deploy/frontend/`, `deploy/cron-manager/`, `deploy/sandbox/`, `deploy/env/`, `deploy/scripts/` (minus `deploy_eval.sh`), `deploy/README.md`, `.github/workflows/` |
| Web backend | `backend/penny/api/` (incl. `persistence/`, `bridge.py`, `mcp_server.py`, `sandbox_wiring.py`), `backend/penny/auth/`, `backend/penny/billing/`, `backend/penny/households.py` |
| Sandboxes | `backend/penny/sandboxes/`, `backend/penny/sandbox.py`, `sandbox/` (Modal runner project), `lib/` (backend↔sandbox wire protocol — only the sandbox seam uses it) |
| Workspace store | `backend/penny/workspace_store/`, `backend/penny/admin.py` (drives the one-off workspace import) |
| Migrations | **No history moves across repos** — the applied chain stays frozen in core — but the tree *does* relocate inside core: `db/migrations/` + `alembic.ini` + `alembic/` must move under the `penny` package to ship in the wheel (see "Migrations: frozen baseline + two forward chains") |
| Tests | `backend/tests/` files covering api/auth/billing/persistence/sandbox/workspace-store |

### Stays in `transactoid`

Everything else, notably: `backend/penny/{tools,plugins,agent_factory.py,prompts.py,adapters,services,taxonomy,rules,memory,normalizer,eval,security,observability,cli.py,config.py,bootstrap.py,workspace.py,db.py,schema.py,llm.py,errors.py,utils}`, `backend/.prompts/`, `backend/.agent/skills/`, `backend/configs/`, `backend/scripts/` (pennydb etc.), finance migrations + alembic, `deploy/eval/`, `deploy/scripts/deploy_eval.sh`, `plans/`, `docs/`, `history/`, `REQUIREMENTS.txt`, `AGENTS.md` (both docs get slimmed post-split; `penny-web` gets its own copies of the relevant sections — an editing task, not a filter task).

### In both repos at split time (deliberate temporary duplication)

- `backend/penny/tenancy/` (109 lines) — core needs it until the tenancy
  inversion lands; web owns it long-term. filter-repo keeps the path in both.
- Shared deploy tooling (`deploy/scripts/lib.sh`) — small, duplicated.

### Judgment calls recorded

- `tenancy/` — web's domain long-term (see tenancy design), duplicated interim.
- `workspace_store/` + `admin.py` — move; `cli.py` mounts `penny admin`
  (`app.add_typer(_admin_app)`), so dropping that mount is a required
  phase-4 edit, and `cli.py`'s sync-all-households loop is refactored to the
  single-tenant scope in phase 5; workspace models
  (`WorkspaceHead`/`WorkspacePrefix`/`WorkspaceManifest`) leave core's
  `adapters/db/models.py` for the web overlay schema during post-split refactor.
- `deploy/cron-manager/` — moves: its jobs run `penny <cmd>` but inside the
  backend *app image*, which `penny-web` builds.
- `config.py` — stays whole initially; web repo grows its own config for
  web-only `PENNY_*` vars during refactor.
- `agent_factory.py` splits (agent-loop decision): `_render_system_prompt` +
  toolset assembly stay in core (feeding both `penny mcp` and web's loop);
  `build_agent()` — `Agent`/`InMemorySession`/sandbox construction — moves to
  the web repo. Loop-driving CLI commands (`chat`-style,
  `run-scheduled-report`; they call `build_agent`, cli.py:171) move to a
  web-owned CLI; core's CLI keeps headless service commands (sync, migrate,
  categorize, eval) and gains `mcp` + `daemon`.
- `api/mcp_server.py` moves as planned — it is the *sandbox-facing*
  trusted-side server (capability tokens, tenancy binding), not the harness
  surface; core's `penny mcp` is a new, simpler stdio entrypoint reusing the
  same toolset-passthrough pattern without the website-domain parts.
- `cli.py reap-sandboxes` (cli.py:482-484) imports `penny.api.persistence`
  **and** `penny.sandboxes` — both moves-list modules. The command is invoked
  by the cron-manager (which moves), so the command itself belongs to the web
  domain: it moves to a web-owned CLI entrypoint in phase 3 and is deleted
  from core's `cli.py` in phase 4. (Found by adversarial review — the one
  "stays imports moves" edge in the tree.)
- `Household`/`User` ORM classes (`adapters/db/models.py:72-106`) and the
  ~24 `ForeignKey("households…"/"users…")` edges on finance tables:
  **recommendation** — core models drop the `ForeignKey(...)` declarations
  (bare nullable `Uuid` columns, same declared-but-reserved treatment as the
  tenant triple, each with an inline "host-managed" comment) and the
  `Household`/`User` classes move to web's models; the *DB-level* FK
  constraints are owned by the web overlay chain, which never drops them in
  prod. Any `relationship()` that traverses those edges must be found and
  refactored — validated in the phase-0 prototype.
- `plans/`, `history/`, `docs/` — non-canonical archives stay with this repo;
  copy (don't move) anything web-relevant.

## Git mechanics

Repo is small (~1,168 commits, 37 MB pack) — both filters run in seconds.

### Extraction (non-destructive)

1. Fresh clone → `git filter-repo` with `--paths-from-file` = the "moves" +
   "both" lists, **explicitly ref-scoped** (`--refs main feature/ui`) — never
   the all-refs default. This preserves commit history for those paths
   (author dates, messages, lineage) **since the current path layout**: the
   repo's pre-rebuild era (`legacy/transactoid-cli` lineage, `src/`-rooted
   layout, an in-line ancestor of `main`) used different paths, and
   filter-repo matches literal paths — that older lineage is not recovered,
   and that trade-off is accepted.
2. Push to the new GitHub repo. Carry `feature/ui` (frontend work in flight)
   through the same filter so the branch lands in `penny-web`.

### Clearing (destructive, last)

0. Ref hygiene first: prune the dead local branches (17 `worktree-*`
   branches) and the ~20 stale pre-rebuild `origin/*` branches, or
   explicitly ref-scope the destructive filter to `main` — running
   filter-repo with its all-refs default would rewrite dozens of untracked
   branches and silently desynchronize local copies from same-named origin
   refs.
1. Safety net first: `git bundle` of the full current repo stored outside it,
   plus a `backup/pre-web-split` branch pushed to origin **before** any
   rewrite. ⚠ An unrelated `backup/pre-split` branch already exists from the
   prior Transactoid→Penny rebuild — near-identical name; never confuse or
   delete it when cleaning up this split's safety net.
2. `git filter-repo --invert-paths` with the same path list (minus the
   "both" list) on this repo, ref-scoped per step 0; force-push `main`. The
   list must reflect paths as of the split commit — in particular it must
   NOT touch the relocated migration tree (`penny/db/migrations/`) even
   though old web-shaped migration files under the frozen baseline remain.
3. All commit hashes change: existing clones re-clone; the codex/claude
   worktrees at old hashes are discarded or recreated; open PRs referencing
   old hashes die (accepted).
4. Legacy refs (`backup/pre-split`, `legacy/transactoid-cli`,
   `worktree-agent-*`): decide per-ref whether to keep (they retain pre-split
   full history — keeping them means web code stays reachable in this repo;
   recommendation: keep only as the temporary `backup/pre-web-split`, delete
   once `penny-web` is verified, rely on the offline bundle thereafter).

### Ordering guard

The force-push (step: Clearing) happens **only after** `penny-web` builds,
its tests pass, and its Fly deploys are cut over. Until then this repo is
frozen for web-app changes but otherwise intact — the destructive step is
last, with two escape hatches (bundle + backup branch).

## Migrations: frozen baseline + two forward chains

The core agent depends on tools → facade → models, so the finance schema
authority (models + finance migrations) must live in core. The web app uses
the **same Postgres database** and needs its own schema evolution. An applied
alembic chain cannot be split retroactively — every migration names its
`down_revision`, so extracting the web-shaped entries (019, 021, 023, 026, …)
would leave holes and break `upgrade head` against the already-stamped prod
DB. Structure instead:

1. **Frozen baseline (core repo).** The entire existing chain up to the split
   point stays in `backend/db/migrations/` exactly as-is — including its
   web-shaped entries. It is history: already applied in prod, never edited,
   never renumbered. Prod's `alembic_version` remains valid with no stamping
   surgery.
2. **Core forward chain (core repo, same version table).** New finance-shape
   migrations continue the existing chain. Contract: core migrations touch
   finance-table *shape* only — never RLS policies, never the tenant-column
   constraints, never web tables. The tenant columns are declared-but-reserved:
   core never alters them.
3. **Web overlay chain (web repo, separate version table, e.g.
   `alembic_version_web`).** Starts empty at the split. Owns forward evolution
   of: web tables (conversations, billing, reminders), `households`/`users`,
   tenant-column constraints (NOT NULL, FKs), RLS policies, workspace-store
   tables, and role/grant management for the `run_sql` RO role. May reference
   core objects (same direction as the code dependency: web → core); core
   never references web objects.

**Who applies what:** the web backend's Fly `release_command` (today
`penny migrate`) becomes a two-step: `penny migrate` — the core CLI applying
the core chain, shipped inside the installed git dep — then
`alembic upgrade head` on the web overlay chain. Order matters (overlay may
depend on core objects).

**Packaging is a real sub-project, not a footnote.** Today the wheel ships
only `packages = ["penny"]` (`backend/pyproject.toml:68`), while
`alembic.ini`, `alembic/`, and `db/migrations/` are *siblings* of the
package; `penny.schema._alembic_ini()` papers over this with a
`Path.cwd()/alembic.ini` fallback that only works because today's Docker
image COPYs the whole `backend/` checkout alongside the install. Under a
git-dep install in `penny-web`'s container there is no checkout, both
candidate paths fail, and `penny migrate` cannot find its version scripts.
Required work (a named phase-3 task): relocate the migration tree under the
package (e.g. `penny/db/migrations/` + packaged ini/env), configure
hatchling to include the non-`.py` package data, and rewrite
`_alembic_ini()` to resolve via `importlib.resources`. This is an
*intra-core* path move — it does not move history across repos, but it does
change paths the invert-paths filter list must not touch.

**Version coupling:** web pins core by tag, so web controls when new core
migrations reach prod — an overlay migration that needs a new core migration
bumps the core dep in the same change. Each repo keeps a drift test: core's
existing `test_schema_drift` runs against a DB with only the core chain
applied (models with nullable tenant columns must match); web adds its own
drift/guardrail test asserting the overlay chain touches no finance-shape
objects and that the combined stack matches what its code expects.

**Local dev is unchanged in kind:** core on SQLite builds schema from models
via `create_all` (no alembic at all — tenant columns exist, nullable, unread);
web dev keeps its separate web store (`penny_web.db` / `web.*` schema) exactly
as today.

## Tenancy: single-tenant core, tenancy as a web layer

### How tenancy threads through the code today

`penny/tenancy` is 109 lines: frozen `RequestContext(user_id, household_id,
session_mode)` + a contextvar (`set/get/require`). All enforcement is ambient
off that contextvar and **already no-ops when unset**. Five patterns:

1. **DB facade** (`adapters/db/facade.py`): `before_flush` stamping of
   `(household_id, owner_user_id, visibility)` on new rows; `after_begin`
   RLS GUC stamping on Postgres (incl. the `SECURITY DEFINER` set-once
   wrapper for the read-only `run_sql` role); app-level query scoping
   (`visible_filter`/`_scope_visible`/`_household_scoped`) — the only fence
   on SQLite.
2. **Tools** use the context shallowly, as an *identity* source:
   `plaid_link` (ctx.user_id for link tokens), `delivery` (report
   recipients), `analytics` (`session_for(ctx)`), `onboarding` (forwards ctx
   to an injected resolver).
3. **Per-household caches**: taxonomy service and category-ID cache key on
   `ctx.household_id`.
4. **`agent_factory.build_agent(ctx=...)`** requires a context by design.
5. **Schema**: tenant triple NOT NULL + FKs to `households`/`users` + RLS
   policies, all delivered by the shared alembic chain; `households`/`users`
   are web-domain tables.

### Target design (Option A: Scope-provider seam)

Core keeps the ambient-contextvar *pattern* but owns a minimal `Scope`
protocol carrying exactly the hooks the five patterns need:

- `stamp_values() -> dict` — row-stamp values at flush (local: `{}`)
- `query_filter(model) -> predicate | None` — app-level scoping (local: `None`)
- `configure_transaction(conn)` — GUC/RLS stamping (local: no-op)
- `cache_key` — partition key for taxonomy/category caches (local: constant)
- identity facts: `user_ref`, report recipients (local: env/workspace config)

Core ships `LocalScope` as the default; tools, `agent_factory`, and the
facade lose every `penny.tenancy` import and call scope hooks instead.
`penny-web` implements `RequestScope(RequestContext)` — today's
`visible_filter`/GUC/stamping behavior verbatim — and sets it per request.
The deployed eval/cron path (`eval/job.py` imports `cron_principal_from_env`
today) keeps a **core-owned** env-derived scope — a `FixedEnvScope` reading
generic scoping env vars that web's deploy config populates — never an
injected web object, which would invert the one-directional dependency.

Schema: tenant columns stay *declared* on core models but nullable and
documented host-managed; core never reads them. NOT NULL, the FKs,
`households`/`users`, workspace-store tables, and RLS policies move to a
**web-owned overlay alembic chain** (separate version table, same Postgres
DB). The already-applied interleaved chain stays frozen in this repo as the
historical baseline; new finance-shape migrations continue core's chain,
new tenancy/web-shape migrations go on web's chain. Locally on SQLite the
tenant columns exist and stay NULL.

### How core queries are written (single user vs. multi-user household)

The key move: **single-tenant core does not mean "a household with one user
hard-coded" — it means no tenancy predicate at all.** Locally, the database
*is* the boundary: one SQLite file (or one isolated Postgres DB for the eval)
holds exactly one person's data, so an unscoped query is already correct.
Core query methods are written scope-neutral and pass through one hook:

```python
# core facade — no tenancy vocabulary, one seam
def list_plaid_transactions(self, session):
    q = session.query(PlaidTransaction)
    q = current_scope().scope_query(q, PlaidTransaction)
    return q.all()

class LocalScope:                       # core default
    def scope_query(self, q, model):    # the whole DB is mine
        return q

class RequestScope:                     # web repo
    def scope_query(self, q, model):    # today's visible_filter, verbatim
        base = model.household_id == self.ctx.household_id
        if self.ctx.session_mode is SessionMode.JOINT:
            return q.filter(base & (model.visibility == "shared"))
        return q.filter(base & ((model.owner_user_id == self.ctx.user_id)
                                | (model.visibility == "shared")))
```

All multi-user semantics — households, owner-vs-shared visibility, joint
sessions — live inside `RequestScope`'s predicate (plus RLS as the second
fence in prod). This works because the tenant columns stay *declared* on core
models (nullable, reserved): the injected predicate needs mapped attributes
to filter on, even though core itself never reads them. The same pattern
covers the other directions:

- **Writes:** `LocalScope.stamp_values()` returns `{}` — rows keep NULL
  tenant columns locally (NOT NULL lives in the web overlay chain, so SQLite
  never complains). `RequestScope` returns the (household, owner, visibility)
  triple, exactly what `_stamp_tenant_columns` fills today.
- **Identity without tenancy:** core still has a *user* — for Plaid link
  tokens, report recipients — but as identity facts on the scope
  (`scope.user_ref`, `scope.report_recipients()`), which `LocalScope` reads
  from workspace config (e.g. a UUID minted once into the workspace dir) and
  `RequestScope` resolves from the web `users` table.
- **`run_sql` / raw SQL:** unscoped locally (correct — one person's DB);
  fenced by RLS + the read-only role in web prod, where
  `scope.configure_transaction(conn)` stamps the GUCs.
- **Household-keyed caches** (taxonomy, category IDs): keyed by
  `scope.cache_key` — a constant locally, `household_id` on web.

### Interim state (Option C, split day — fallback only)

`penny/tenancy` ships in both repos; core runs with a fixed local principal
(auto-provisioned constant household/user, today's `PENNY_DEV_*` mechanism).
Everything runs unchanged on day one; the Option A refactor then hollows
tenancy out of the core and deletes the duplicated module last.

### Alternatives considered and rejected

- **RLS-only inversion** (core drops all tenancy; web enforces purely in
  Postgres via GUC column defaults + RLS + externally attached listeners):
  identity and cache-key seams reappear anyway, the app-level
  belt-and-suspenders filter is lost, and isolation becomes untestable
  without Postgres. Rebuilds half of Option A, less explicitly.
- **Option C as end state** (fixed local principal forever): near-zero
  refactor but tools/schema stay tenancy-shaped and every tenancy change
  spans both repos.

## Phases

0. **Tenancy-inversion prototype (mono-repo, on a branch) → USER REVIEW.**
   Prove the Scope seam while everything is still in one repo, where
   iteration is cheap. Vertical slice exercising every hook kind:
   - `Scope` protocol + `LocalScope` in core; `RequestScope` shim wrapping
     today's `RequestContext` so the web app runs unchanged.
   - Facade: replace the tenancy internals (`_scope_visible`,
     `_household_scoped`, `_stamp_tenant_columns` values,
     `_apply_rls_settings`) with scope hooks.
   - One identity tool (`plaid_link`) + one scoped tool (`analytics`), the
     taxonomy cache key, and `build_agent` without a `ctx` requirement.
   - Full test suite + the `postgres` RLS suite green; a short findings note.
   **Gate:** user reviews the prototype branch. Then decide: land the full
   inversion pre-split (recommended if the seam holds — the split then moves
   `tenancy/` wholly to web with no duplication), or fall back to the
   Option C interim (duplicate `tenancy/`, fixed local principal) and finish
   the inversion post-split.
1. **Prep.** Land or explicitly park in-flight branches (`feature/ui` moves
   to `penny-web`); create the bundle + `backup/pre-web-split`; freeze
   web-app changes in this repo.
2. **Extract.** filter-repo a fresh clone down to the "moves" + "both"
   lists; push as `penny-web` with `feature/ui` carried over.
3. **Make `penny-web` green.** Own `pyproject.toml`/uv lock pinning
   `transactoid` as a git dep; rename its backend package (its `penny/api`
   cannot shadow the installed `penny` package — e.g. `pennyweb/`), rewrite
   imports; CI; make core's migration tree package data so `penny migrate`
   works from the git-dep install; switch the backend `release_command` to
   the two-step core-chain-then-overlay-chain form; cut Fly deploys
   (backend, frontend, cron-manager) and Modal sandbox over to the new repo.
   Verify prod deploy end-to-end.
4. **Clear this repo.** filter-repo `--invert-paths` + force-push; recreate
   worktrees; prune `bootstrap` (web-schema creation), `config.py` web vars,
   web tests, the `penny admin` CLI mount; slim
   `AGENTS.md`/`REQUIREMENTS.txt`; uv workspace collapses to `backend/` only.
5. **Complete the tenancy inversion (whatever phase 0's decision left).**
   Core: delete `penny/tenancy` and any fixed-principal shim; refactor
   `cli.py`'s sync-all-households loop to single-tenant. Web: stand up the
   overlay migration chain (NOT NULL/FKs/RLS/households/users/workspace
   tables + `run_sql` role grants), move workspace models out of core,
   replace `cron_principal_from_env` with an injected scope.
6. **Local-first surface (the core deliverable).** `penny mcp` stdio
   entrypoint exposing the toolsets verbatim, with the dynamic prompt blocks
   ({{CURRENT_DATE}}, {{DATABASE_SCHEMA}}, {{CATEGORY_TAXONOMY}},
   {{AGENT_MEMORY}}) rendered fresh into MCP `initialize` instructions, and a
   static agents-doc (CLAUDE.md/AGENTS.md) carrying identity/behavior —
   harnesses load it natively when opened as a project. `penny daemon`
   running sync (which runs the categorizer agent) beside it; `sync_status`
   tool over DB watermarks. Workspace = plain directory reference; CLI
   defaults sane with zero env.

   **Fast-follows (recorded, deliberately out of initial scope):**
   - CLI onboarding flow — connect Plaid, budget setup, first-run experience.
   - Harness poll-and-decide guidance: system instructions teaching the
     user's harness to poll `sync_status` and choose between waiting for a
     sync threshold or proceeding with stale data.
   - `~/.transactoid` → `~/.penny` workspace rename (one-line fallback
     check), if ever.

## Risks & open questions

- **Two-alembic-chain discipline**: overlay chain must never touch
  finance-shape objects and vice versa; needs a drift-test analogue in each
  repo — as a **hard CI gate from day one**, not aspiration. Precedent says
  the line blurs: ~15 of the 29 historical migrations are tenancy/web-shaped
  and interleaved with finance work (e.g. 016 alters `categories`, a genuine
  finance table, *to encode tenancy*). The frozen baseline absorbs that
  history; the gate is what keeps the forward chains honest.
- **Scope-protocol evolution cost**: the phase-0 mono-repo prototype
  mitigates the *initial* design risk, but after the split any change to the
  Scope contract (new hook, changed signature) is a cross-repo
  tag-bump-and-update round trip with no mono-repo escape hatch. Keep the
  protocol minimal and additive; batch contract changes.
- **Model/DB divergence is deliberate and must be labeled**: core models
  declare tenant columns nullable while prod Postgres has them NOT NULL
  (frozen migration 014). Every such column carries an inline
  "host-managed; NOT NULL + FK enforced by the web overlay chain" comment so
  a future reader (human or agent) doesn't "fix" the mismatch.
- **Interim window (phases 1–3)**: `penny-web` exists but this repo still
  holds web paths; the freeze in phase 0 prevents divergence. Keep the
  window short.
- **Cross-repo versioning**: web pins core by tag; core API changes now
  require a tag bump + web update (the agent-harness workflow, accepted).
- **`run_sql` blast radius** improves post-split: the finance-only facade and
  read-only role remain core; web data lives in its own schema as today.
- Open: GitHub settings for `penny-web` (branch protection, Fly/Modal deploy
  secrets move there); whether `legacy/transactoid-cli` history is kept
  anywhere permanent; how much authority each harness actually grants MCP
  `initialize` instructions (client-dependent — validate on Claude Code,
  Codex, pi.dev during phase 6).
