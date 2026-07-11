# Alembic as Sole Schema Authority on Postgres — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `alembic upgrade head` the *only* mechanism that evolves a durable Postgres schema, run once per deploy — and make "`create_all` on a Postgres DB" impossible to do by accident. Keep `create_all` where it is correct and load-bearing: ephemeral SQLite (local dev, the test suite, the eval store).

**Architecture:** One schema authority *per environment*, chosen by dialect.
- **Postgres (prod/staging):** schema is owned by the alembic migration chain, applied via a Fly `release_command` (`penny migrate`) that runs **once** in an ephemeral machine before the app machines start. The app's `bootstrap()` never touches the Postgres schema.
- **SQLite (dev/test/eval):** schema is built from the models via `create_all` — fast, dialect-portable, always model-accurate. Unchanged.
- **Guardrails:** `create_schema()` / `create_web_schema()` raise if called against a non-SQLite engine (fail loud, no silent half-migration). A CI drift test proves the models (`create_all`) and the migration chain (`alembic upgrade head`) describe the same schema.

**Tech Stack:** SQLAlchemy 2.x, Alembic (`backend/alembic` env + `backend/db/migrations` version scripts), Typer CLI (`penny/cli.py`), Fly.io (`deploy/backend/`), pytest.

## Why this, and why now

`bootstrap()` runs `create_all` on **every** startup, prod included (`penny/api/main.py:73` → `bootstrap()` → `db.create_schema()`). `create_all` creates only *missing tables* — never `ALTER`s, never advances `alembic_version`. On Postgres, where migrations are authoritative, this makes `create_all` a **second, silent schema authority** that collides with alembic. That is the root cause of the phase-3 cutover pain: create_all had pre-made the tenancy tables empty, so `alembic upgrade` died on `relation "households" already exists`, and prod threw `column categories.household_id does not exist` because create_all can't add a column to an existing table.

It is currently **dormant** (post-cutover every table exists, so create_all is a no-op) — but the trap re-arms the moment a future migration adds a table. Fix it before the next schema-changing feature.

**This is the scoped fix (was "option 1").** It is deliberately *not* "delete `create_all` everywhere" (was "option 2"): investigation showed `create_all` is correct and load-bearing in 57 test files (via `conftest.py:92`), the eval store, and the web store, and that the migration chain already replays clean on SQLite. `create_all` was never the bug — running it on a durable Postgres DB *without stamping* was. So we forbid it exactly there.

## Global Constraints

- **Dev loop must not change.** `uv run uvicorn penny.api.main:app` against SQLite must still work with zero migration steps. The 624-test suite (SQLite via `tests/conftest.py`) must keep building schema via `create_all` and stay fast.
- **First prod deploy of this change must be a no-op.** Prod is already at head (`024`), so `penny migrate` must exit 0 having applied nothing.
- **Segregation (AGENTS.local.md):** the finance façade (`Base`) and the website store (`WebBase`) stay separate. Do not merge their schema mechanisms; treat each explicitly.
- **Deploy vs app (AGENTS.local.md):** the *when* of migrations lives in the deploy domain (`deploy/backend/fly.toml` `release_command`); app code only exposes the *how* (`penny migrate`). The app never branches on deploy topology.
- **Empirically verified precondition:** `DATABASE_URL=sqlite:///tmp.db alembic upgrade head` replays `000→024` clean to head (batch ops + dialect guards already present). The drift test therefore runs on SQLite in CI — no Postgres required.

---

## Task 1: Ship the migration version scripts in the backend image

**Files:**
- Modify: `deploy/backend/Dockerfile`

**Interfaces:**
- Produces: `/app/db/migrations/` present in the runtime image, so in-container `alembic upgrade head` (Task 6) can find the version scripts referenced by `alembic.ini`'s `version_locations = %(here)s/db/migrations`.

Today the Dockerfile copies `backend/alembic` + `alembic.ini` but **not** `backend/db/migrations` — so in-container alembic finds no revisions (this is why the cutover was run from a laptop).

- [ ] **Step 1: Add the COPY to the builder stage**

In `deploy/backend/Dockerfile`, after the existing `COPY backend/alembic ./alembic` / `COPY backend/alembic.ini ./alembic.ini` lines:

```dockerfile
COPY backend/db/migrations ./db/migrations
```

- [ ] **Step 2: Add the COPY to the production stage**

Beside the existing `COPY --from=builder /app/alembic /app/alembic`:

```dockerfile
COPY --from=builder /app/db/migrations /app/db/migrations
```

- [ ] **Step 3: Verify the image can see the revisions**

Build locally and check (or defer to Task 6's release run):
```
docker build -f deploy/backend/Dockerfile -t penny-mig-check . && \
  docker run --rm penny-mig-check sh -lc 'ls db/migrations | tail -3'
```
Expected: `022_*.py 023_*.py 024_*.py` listed.

- [ ] **Step 4: Commit**

```bash
git add deploy/backend/Dockerfile
git commit -m "build(backend): ship db/migrations in the image so alembic can run in-container"
```

---

## Task 2: `penny/schema.py` — the single migration entry point

**Files:**
- Create: `backend/penny/schema.py`
- Test: `backend/tests/test_schema_authority.py`

**Interfaces:**
- Produces: `upgrade_to_head(database_url: str | None = None) -> None` — runs `alembic upgrade head` in-process. Idempotent (no-op at head). Used by Task 3 (`penny migrate`) and Task 7 (drift test).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_authority.py
from sqlalchemy import create_engine, inspect
from penny.schema import upgrade_to_head

def test_upgrade_to_head_builds_full_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    upgrade_to_head(url)
    tabs = inspect(create_engine(url)).get_table_names()
    assert "households" in tabs
    assert "household_id" in {c["name"] for c in inspect(create_engine(url)).get_columns("categories")}
    # idempotent: a second run is a no-op, not an error
    upgrade_to_head(url)
```

- [ ] **Step 2: Run it, verify it fails** — `uv run pytest tests/test_schema_authority.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
# backend/penny/schema.py
"""Schema authority: alembic owns durable (Postgres) schemas; create_all owns
ephemeral SQLite (dev/test/eval). This module is the single in-process entry
point for applying migrations. See docs/.../2026-07-09-alembic-sole-authority-on-postgres.md
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def upgrade_to_head(database_url: str | None = None) -> None:
    """Apply alembic migrations to head. Idempotent (no-op when already at head).

    ``env.py`` honors ``DATABASE_URL``; passing ``database_url`` sets the config
    url explicitly (used by tests and the CLI). ``%(here)s`` in alembic.ini
    resolves to ``backend/``, so ``version_locations`` finds db/migrations.
    """
    cfg = Config(str(_ALEMBIC_INI))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
```

- [ ] **Step 4: Run the test, verify it passes** — `uv run pytest tests/test_schema_authority.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/schema.py backend/tests/test_schema_authority.py
git commit -m "feat(schema): add upgrade_to_head() as the single alembic entry point"
```

---

## Task 3: `penny migrate` CLI command (the release front door)

**Files:**
- Modify: `backend/penny/cli.py`

**Interfaces:**
- Consumes: `penny.schema.upgrade_to_head` (Task 2).
- Produces: `penny migrate` — invoked by the Fly `release_command` (Task 6). Non-zero exit on failure so a bad migration fails the deploy.

`cli.py` is the sanctioned headless front door (AGENTS.local.md); it may drive app code. It already loads env once at import.

- [ ] **Step 1: Add the command** (near the other `@app.command(...)` definitions)

```python
@app.command("migrate")
def migrate_cmd() -> None:
    """Apply alembic migrations to head (the prod release step)."""
    from penny.schema import upgrade_to_head

    upgrade_to_head()  # env.py reads DATABASE_URL
    logger.info("penny migrate: schema at head")
```

- [ ] **Step 2: Smoke-test against SQLite**

```
DATABASE_URL="sqlite:////tmp/cli_mig.db" uv run penny migrate
```
Expected: exits 0, logs "schema at head"; `/tmp/cli_mig.db` has the tables.

- [ ] **Step 3: Commit**

```bash
git add backend/penny/cli.py
git commit -m "feat(cli): add `penny migrate` — the prod release migration front door"
```

---

## Task 4: Fail-loud guard — `create_all` may never touch Postgres

**Files:**
- Modify: `backend/penny/adapters/db/facade.py` (`create_schema`, ~line 332)
- Modify: `backend/penny/api/persistence/engine.py` (`create_web_schema`, ~line 116)
- Test: `backend/tests/test_schema_authority.py`

**Interfaces:**
- Produces: `create_schema()` / `create_web_schema()` raise `RuntimeError` on a non-SQLite engine. This is the backstop that makes the original footgun impossible; the intended callers are gated in Task 5.

- [ ] **Step 1: Write the failing test**

```python
def test_create_schema_refuses_postgres(monkeypatch):
    import pytest
    from penny.adapters.db.facade import DB
    db = DB(url="postgresql://user:pw@localhost/nonexistent")  # not connected
    with pytest.raises(RuntimeError, match="alembic"):
        db.create_schema()
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Add the guard in `facade.py`**

```python
def create_schema(self) -> None:
    """Create tables from the models. SQLite (ephemeral dev/test) ONLY.

    On Postgres the schema is owned by alembic — run `penny migrate`
    (upgrade head). create_all can't ALTER/backfill/enable RLS and would
    silently half-migrate, so it is refused here.
    """
    if self._engine.dialect.name != "sqlite":
        raise RuntimeError(
            "create_schema()/create_all is SQLite-only; Postgres schema is "
            "alembic-owned. Run `penny migrate` (alembic upgrade head)."
        )
    Base.metadata.create_all(self._engine)
```

- [ ] **Step 4: Add the same guard in `engine.py::create_web_schema`**

```python
def create_web_schema() -> None:
    engine = get_web_engine()
    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            "create_web_schema()/create_all is SQLite-only; on Postgres the "
            "web.* tables are owned by the alembic chain (`penny migrate`)."
        )
    WebBase.metadata.create_all(engine)
```

Note: the Postgres `CREATE SCHEMA IF NOT EXISTS web` that lived here moves to being alembic's responsibility — confirm a migration establishes the `web` schema before the first `web.*` table (see Risks). If none does, add a tiny migration or keep a Postgres-only `CREATE SCHEMA` in `penny migrate`'s path, *not* a `create_all`.

- [ ] **Step 5: Run tests, verify green.**

- [ ] **Step 6: Commit**

```bash
git add backend/penny/adapters/db/facade.py backend/penny/api/persistence/engine.py backend/tests/test_schema_authority.py
git commit -m "feat(schema): fail loud if create_all is called against a Postgres engine"
```

---

## Task 5: Dialect-gate the callers (`bootstrap`, web store, eval store)

**Files:**
- Modify: `backend/penny/bootstrap.py` (~lines 24-33)
- Modify: `backend/penny/api/persistence/store.py` (`ConversationStore.create_schema`, ~line 97)
- Modify: `backend/penny/eval/job.py` (~line 74), `backend/penny/eval/fixture.py` (~line 92)
- Test: `backend/tests/test_schema_authority.py`

**Interfaces:**
- Consumes: the Task-4 guard, `get_db().dialect`.
- Produces: on Postgres, none of these call `create_all`; the schema is assumed alembic-managed. On SQLite they behave exactly as today.

Add a `dialect` property to the façade if absent:
```python
# facade.py
@property
def dialect(self) -> str:
    return self._engine.dialect.name
```

- [ ] **Step 1: Write the failing test** — bootstrap on Postgres must not call `create_all`:

```python
def test_bootstrap_does_not_create_all_on_postgres(monkeypatch):
    calls = []
    from penny.adapters.db import facade
    monkeypatch.setattr(facade.DB, "create_schema", lambda self: calls.append("create"))
    monkeypatch.setattr("penny.bootstrap.get_db", lambda: _fake_pg_db())  # dialect=="postgresql"
    from penny.bootstrap import bootstrap
    bootstrap()
    assert calls == []  # alembic owns Postgres; no create_all
```

- [ ] **Step 2: Run it, verify it fails.**

- [ ] **Step 3: Gate `bootstrap()`**

```python
def bootstrap() -> None:
    """Ensure schema + seed the dev identity. SQLite builds from models;
    Postgres schema is alembic-owned (applied by `penny migrate` at release)."""
    db = get_db()
    if db.dialect == "sqlite":
        db.create_schema()
        from .api.persistence.engine import create_web_schema
        create_web_schema()
    # Postgres: schema owned by alembic (deploy runs `penny migrate`).
    _seed_dev_household()  # no-op on prod (PENNY_DEV_* unset)
```

- [ ] **Step 4: Gate the web store + eval store callers**

- `store.py::ConversationStore.create_schema` — only build on SQLite; on Postgres, no-op (chain owns `web.*`).
- `eval/job.py:74`, `eval/fixture.py:92` — the eval store is SQLite in practice; gate the `create_schema()` calls the same way, or route them through `upgrade_to_head` if an eval run ever targets Postgres. (Confirm the eval DB dialect during implementation; if always SQLite, a comment + the Task-4 guard suffice.)

- [ ] **Step 5: Run the full suite** — `uv run pytest -q`. The 624-test suite (SQLite) must stay green: `conftest.py:92` still wraps `create_schema` (SQLite), which is unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/penny/bootstrap.py backend/penny/api/persistence/store.py backend/penny/eval/*.py backend/penny/adapters/db/facade.py backend/tests/test_schema_authority.py
git commit -m "feat(schema): gate create_all callers to SQLite; Postgres schema via alembic"
```

---

## Task 6: Run prod migrations via Fly `release_command`

**Files:**
- Modify: `deploy/backend/fly.toml`

**Interfaces:**
- Consumes: `penny migrate` (Task 3), the image with migrations (Task 1).
- Produces: every backend deploy runs `penny migrate` once in an ephemeral release machine before the app machines start — no per-machine race.

- [ ] **Step 1: Add the deploy stanza**

```toml
[deploy]
  release_command = "penny migrate"
```

(`release_command` runs in a temporary machine from the *new* image with the app's env/secrets, so `DATABASE_URL` resolves exactly as the app's does.)

- [ ] **Step 2: Confirm the first run is a no-op**

Prod is at `024`. On the first deploy of this change the release log must show alembic connecting and applying **nothing** (already at head), exit 0. If the release fails, the deploy aborts and the old machines keep serving — safe by design.

- [ ] **Step 3: Commit**

```bash
git add deploy/backend/fly.toml
git commit -m "deploy(backend): apply migrations via release_command (penny migrate)"
```

---

## Task 7: Drift guard — models ≡ migrations (CI, on SQLite)

**Files:**
- Test: `backend/tests/test_schema_drift.py`

**Interfaces:**
- Consumes: `upgrade_to_head` (Task 2), `Base` (finance models), `WebBase` (web models).
- Produces: a CI test that fails if the models and the migration chain diverge (e.g. a model column added without a migration). Runs on **SQLite** — no Postgres marker — because the chain is proven SQLite-clean.

Use an **introspection diff**, not autogenerate: on SQLite the Postgres-only constructs (RLS, GUC, server defaults) are guarded out of *both* the models and the migrations, so comparing table+column sets is apples-to-apples and free of autogenerate's Postgres false-positives.

- [ ] **Step 1: Write the test**

```python
# tests/test_schema_drift.py
from sqlalchemy import create_engine, inspect
from penny.schema import upgrade_to_head
from penny.adapters.db.models import Base

def _schema(engine):
    insp = inspect(engine)
    return {t: sorted(c["name"] for c in insp.get_columns(t)) for t in insp.get_table_names()}

def test_models_match_migrations(tmp_path):
    mig_url = f"sqlite:///{tmp_path / 'mig.db'}"
    upgrade_to_head(mig_url)
    migrated = _schema(create_engine(mig_url))
    migrated.pop("alembic_version", None)

    mdl = create_engine(f"sqlite:///{tmp_path / 'mdl.db'}")
    Base.metadata.create_all(mdl)
    models = _schema(mdl)

    assert models == migrated, (
        "models drifted from migrations — a model change needs a migration.\n"
        f"only in models: {set(models) - set(migrated)}\n"
        f"only in migrations: {set(migrated) - set(models)}"
    )
```

- [ ] **Step 2: Run it** — `uv run pytest tests/test_schema_drift.py -q`. Expected PASS today. If it fails, it has found a real, pre-existing drift between `models.py` and the chain — investigate and reconcile (that is the test doing its job).

- [ ] **Step 3: (Optional) extend to `WebBase`** — the web models vs the `web.*` migrations. Because the web tables are guarded off SQLite in the finance chain, this needs the web store's own SQLite `create_all` compared against a SQLite build of the web migrations; scope during implementation, or defer with a `# TODO` and a note in the plan's Risks.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_schema_drift.py
git commit -m "test(schema): CI drift guard — models must equal the migration chain"
```

---

## Task 8: Documentation

**Files:**
- Modify: `AGENTS.md` (the "Databases" section), `backend/CLAUDE.md` if it duplicates, `REQUIREMENTS.txt` (Technical Invariants)

- [ ] **Step 1: Update the Databases section** — replace "schema via `bootstrap()` on startup (`create_all` …)" with the real model: SQLite dev/test uses `create_all`; Postgres schema is alembic-owned and applied by `penny migrate` (release_command); `create_all` is refused on Postgres. Remove the now-false "create_all-managed prod" framing (and align the stale cutover-README claim).

- [ ] **Step 2: Add the invariant to `REQUIREMENTS.txt`** — "Durable (Postgres) schema is evolved only by alembic migrations, applied once per deploy; `create_all` is forbidden on Postgres (enforced by `test_schema_authority` + `test_schema_drift`)."

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md REQUIREMENTS.txt backend/CLAUDE.md
git commit -m "docs: alembic owns Postgres schema; create_all is SQLite-only"
```

---

## Risks & decisions to resolve during implementation

1. **The `web` schema on Postgres.** `create_web_schema` currently does `CREATE SCHEMA IF NOT EXISTS web` before `create_all`. Once `create_all` is gated off Postgres, confirm a migration (or `penny migrate`'s path) establishes the `web` schema before the first `web.*` table. If migrations `019+` assume the schema exists, add a one-line `op.execute("CREATE SCHEMA IF NOT EXISTS web")` guard at the head of the first web migration — do **not** reintroduce a Postgres `create_all`.
2. **Eval store dialect.** Confirm `eval/job.py` / `eval/fixture.py` only ever target SQLite. If an eval run can point at Postgres, route its schema creation through `upgrade_to_head` instead of gating to a no-op.
3. **`WebBase` drift coverage (Task 7 Step 3).** The finance drift test is straightforward; the web drift test needs a SQLite build of the web migrations vs `WebBase.create_all`. Acceptable to land finance drift first and follow up.
4. **Concurrency.** `release_command` (one ephemeral machine) sidesteps the two-app-machine race entirely — do not fall back to running migrations in `bootstrap()` on Postgres.
5. **Rollback.** This change is code-only and reversible; the first deploy is a no-op against the already-migrated prod. No data operation, no snapshot required.

## Out of scope (explicitly)

- Removing `create_all` from dev/tests/eval (the "option 2" path): rejected — `create_all` is correct and load-bearing there (fast, model-accurate, dialect-portable), and removing it means rewriting ~57 test fixtures + giving the web store its own alembic chain for marginal benefit.
- Moving local dev onto Postgres (the fullest-parity "option 3"): a separate product decision about dev onboarding + local RLS parity.

## Self-review

- **Coverage:** every symptom (prod 500 from missing ALTER; cutover collision; silent half-migration) is closed by Tasks 4-6; Tasks 1-3 make the Postgres alembic path actually runnable; Task 7 prevents future model/migration drift; Task 8 corrects the record.
- **Types/signatures:** `upgrade_to_head(database_url: str | None)` is used identically in Task 3 (CLI) and Task 7 (test); `DB.dialect: str` added in Task 5 and consumed there.
- **No placeholders:** each code step shows the actual code; each command shows the expected result.
- **Effort:** ~half a day. Tasks 1-6 are small and mechanical; Task 7 (drift test) is the one needing care to keep the comparison clean.
