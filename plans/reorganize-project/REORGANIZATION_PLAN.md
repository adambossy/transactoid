# Directory Structure Reorganization — Refined Proposal

## Current State
The project currently uses a **flat root-level directory structure** with the following layout:
- `adapters/`, `frontends/`, `orchestrators/`, `tools/`, `services/`, `models/`, `ui/`, `scripts/`, `tests/`
- ⚠️ **Issue 1**: Root-level directories make it harder to distinguish between source code, tests, and project artifacts
- ⚠️ **Issue 2**: No clear separation between domain types and business logic
- ⚠️ **Issue 3**: `tools/ingest/` is **empty except for `__init__.py`** — effectively obsolete
- ⚠️ **Issue 4**: `tools/sync/sync_tool.py` is the only active ingestion mechanism
- ⚠️ **Issue 5**: Uses `ui/` for some interfaces but calls the package `frontends/` in other places

---

## Analysis: What's Actually Used

### Current `tools/ingest/` Status
- **Directory**: `tools/ingest/`
- **Contents**: 
  - `__init__.py` (empty module)
  - `adapters/` (empty directory)
- **References in codebase**: Zero active imports of `ingest`
- **Notes**: The README and CLAUDE.md reference planned CSV ingestion with bank adapters, but this was never implemented
- **Reality**: `SyncTool` (in `tools/sync/sync_tool.py`) directly calls Plaid's API; no CSV ingestion exists

### Current `tools/sync/` Status
- **File**: `tools/sync/sync_tool.py`
- **Does**: Calls Plaid's transaction sync API, categorizes results via LLM
- **Used by**: `orchestrators/transactoid.py`, `ui/cli.py`, `scripts/run.py`
- **Is**: The only active transaction ingestion mechanism in the codebase

### Shared Types in `models/`
- `models/transaction.py` — `Transaction`, `PersonalFinanceCategory` TypedDicts
- **Zero dependencies**: Can be imported everywhere without pulling in business logic or infrastructure
- Single source of truth for transaction types across all layers
- Imported across tools, infra, core, and ui packages

### Taxonomy Organization
- `core/taxonomy.py` currently couples domain logic with error definitions
- `services/taxonomy_generator.py` handles YAML loading (I/O)
- Should be grouped as a cohesive subdomain: `src/transactoid/taxonomy/`
  - `core.py` — Taxonomy class and validation logic
  - `generator.py` — Load from YAML, instantiate Taxonomy
  - `errors.py` — Taxonomy-specific exceptions

### Interface Inconsistency
- `ui/` directory exists with `cli.py`
- `frontends/` directory also exists with `chatkit_server.py`, `mcp_server.py`, `simple_store.py`
- Naming is inconsistent; both serve the same purpose (user-facing interfaces)

---

## Proposed Changes

### 1. Consolidate UI Directories and Reorganize Adapters
**Current state**: 
- `ui/` directory exists with `cli.py`
- `frontends/` directory exists with `chatkit_server.py`, `mcp_server.py`, `simple_store.py`
- `adapters/` exists at top level with `openai_adapter.py` (Tools → OpenAI SDK), `chatkit_adapter.py`, `mcp_adapter.py`

**Action**:
1. Move orchestration infrastructure adapter:
   - Move `adapters/openai_adapter.py` → `orchestrators/openai_adapter.py` (Tools → OpenAI format)
2. Reorganize UI-specific adapters into UI layer:
   - Move `adapters/chatkit_adapter.py` → `ui/chatkit/adapter.py`
   - Move `frontends/chatkit_server.py` → `ui/chatkit/server.py`
   - Move `adapters/mcp_adapter.py` → `ui/mcp/adapter.py`
   - Move `frontends/mcp_server.py` → `ui/mcp/server.py`
3. Move `frontends/simple_store.py` → `ui/simple_store.py`
4. Delete empty `adapters/` and `frontends/` directories
5. Update imports throughout codebase

**Result**:
```
ui/
├── __init__.py
├── cli.py                         # Typer CLI entrypoint
├── simple_store.py                # Store interface
├── chatkit/
│   ├── __init__.py
│   ├── adapter.py                 # OpenAI Agents → ChatKit adapter
│   └── server.py                  # ChatKit server
└── mcp/
    ├── __init__.py
    ├── adapter.py                 # OpenAI Agents → MCP adapter
    └── server.py                  # MCP server
```

**Benefits**:
- Single, consistent namespace for all user-facing interfaces
- Framework adapters live with their UI servers (cohesion)
- Fewer top-level directories (reduces cognitive load)
- Aligns with project terminology

---

### 2. Create Nested `src/` Structure
**Purpose**: Separate source code, tests, and project artifacts using industry standard layout.

**Action**:
1. Create `src/transactoid/` directory structure mirroring current root packages
2. Move source packages into `src/transactoid/`
3. Keep `tests/` at root level (mirrors `src/` layout)
4. Keep `scripts/`, `configs/`, `db/`, `docs/`, `models/` at root level

**Result structure**:
```
transactoid/
├── src/transactoid/               # All source code
│   ├── core/                      # General domain logic
│   │   ├── __init__.py
│   │   ├── errors.py              # Domain exceptions (non-taxonomy)
│   │   └── [other core logic]
│   ├── taxonomy/                  # Taxonomy bounded context
│   │   ├── __init__.py
│   │   ├── core.py                # Taxonomy class & logic
│   │   ├── generator.py           # Load from YAML
│   │   └── errors.py              # Taxonomy-specific exceptions
│   ├── infra/                     # Infrastructure & integrations
│   ├── tools/                     # Tool implementations (defines Tool protocol)
│   ├── orchestrators/             # Agent orchestration
│   │   ├── __init__.py
│   │   ├── transactoid.py         # Main agent orchestrator
│   │   └── openai_adapter.py      # Adapts tools to OpenAI SDK format
│   ├── ui/                        # User interfaces + UI-specific adapters
│   │   ├── __init__.py
│   │   ├── cli.py                 # Typer CLI
│   │   ├── simple_store.py        # Simple store interface
│   │   ├── chatkit/               # ChatKit UI
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # OpenAI Agents → ChatKit
│   │   │   └── server.py          # ChatKit server
│   │   └── mcp/                   # MCP UI
│   │       ├── __init__.py
│   │       ├── adapter.py         # OpenAI Agents → MCP
│   │       └── server.py          # MCP server
│   ├── prompts/                   # Prompt templates
│   └── utils/                     # Utilities
│
├── models/                        # Shared types (zero dependencies)
│   ├── __init__.py
│   └── transaction.py             # Transaction, PersonalFinanceCategory
│
├── tests/                         # Tests (mirrors src/ layout)
├── scripts/                       # Standalone scripts
├── configs/                       # Config files
├── db/                            # Database artifacts
├── docs/                          # Documentation
└── [root config files]
```

**Benefits**:
- Clear separation: source vs. tests vs. project artifacts
- Follows Python packaging best practices
- Reduces root-level clutter
- Easier to identify package contents vs. development infrastructure
- `models/` at root can be imported everywhere with no dependencies

---

### 3. Remove `tools/ingest/` Entirely
**Current state**:
- Empty package with no implementations (only `__init__.py` and empty `adapters/` dir)
- No active code paths reference it
- README.md and CLAUDE.md document planned CSV ingestion that was never built
- `SyncTool` is the only real ingestion mechanism (Plaid API calls)

**Action**:
1. Delete `tools/ingest/` directory and all subdirectories
2. Delete `tests/tools/ingest/` test stubs (if any)
3. Remove `ingest` references from `pyproject.toml` if present
4. Update README.md and CLAUDE.md to remove mentions of planned CSV ingestion (or move to roadmap)

**Why**:
- Dead code creates cognitive load
- If/when CSV ingestion is needed, it can be added cleanly later
- Current design (`SyncTool` + LLM categorization) doesn't need intermediate CSV adapters

---

### 4. Keep `tools/sync/` as-is
**Current**: `tools/sync/sync_tool.py`
- ✅ Active implementation (Plaid sync API calls)
- ✅ Handles pagination and error recovery
- ✅ Orchestrates with categorizer for full sync workflow
- ✅ No need to merge or reorganize

**No changes needed**.

---

## Final Proposed Structure

```
transactoid/
│
├── src/transactoid/               # All source code
│   ├── models/                    # Shared types (zero dependencies)
│   │   ├── __init__.py
│   │   └── transaction.py         # Transaction, PersonalFinanceCategory
│   │
│   ├── core/                      # General domain logic
│   │   ├── __init__.py
│   │   ├── errors.py              # Domain exceptions (non-taxonomy)
│   │   └── [other core logic]
│   │
│   ├── taxonomy/                  # Taxonomy bounded context
│   │   ├── __init__.py
│   │   ├── core.py                # Taxonomy class, validation, methods
│   │   ├── generator.py           # Load taxonomy from YAML
│   │   └── errors.py              # Taxonomy-specific exceptions
│   │
│   ├── infra/                     # Infrastructure & integrations
│   │   ├── db/
│   │   ├── cache/
│   │   ├── clients/
│   │   ├── config.py
│   │   └── [other infra]
│   │
│   ├── tools/                     # Tool implementations (defines Tool protocol)
│   │   ├── base.py
│   │   ├── protocol.py
│   │   ├── registry.py
│   │   ├── categorize/
│   │   ├── persist/
│   │   ├── query/
│   │   └── sync/
│   │
│   ├── orchestrators/             # Agent orchestration
│   │   ├── __init__.py
│   │   ├── transactoid.py         # Main agent orchestrator
│   │   └── openai_adapter.py      # Adapts tools to OpenAI SDK format
│   │
│   ├── ui/                        # User interfaces + UI-specific adapters
│   │   ├── __init__.py
│   │   ├── cli.py                 # Typer CLI
│   │   ├── simple_store.py        # Simple store interface
│   │   ├── chatkit/               # ChatKit UI
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # OpenAI Agents → ChatKit
│   │   │   └── server.py          # ChatKit server
│   │   └── mcp/                   # MCP UI
│   │       ├── __init__.py
│   │       ├── adapter.py         # OpenAI Agents → MCP
│   │       └── server.py          # MCP server
│   │
│   ├── prompts/                   # Prompt templates
│   │
│   └── utils/                     # Utilities
│
├── tests/                         # Tests (mirrors src/ layout)
│   ├── conftest.py
│   ├── core/
│   ├── taxonomy/
│   ├── infra/
│   ├── tools/
│   ├── orchestrators/
│   └── ui/
│       ├── test_cli.py
│       ├── chatkit/
│       │   └── test_chatkit_server.py
│       └── mcp/
│           └── test_mcp_server.py
│
├── scripts/                       # Standalone runnable scripts
│   ├── __init__.py
│   ├── run.py                     # Main orchestrator runner
│   ├── plaid_cli.py               # Plaid-specific CLI
│   ├── seed_taxonomy.py           # Load taxonomy from YAML
│   ├── build_taxonomy.py          # Generate taxonomy
│   └── migrate_legacy_categories.py
│
├── configs/                       # Configuration and seed data
│   ├── taxonomy.yaml              # Taxonomy definitions
│   ├── config.example.yaml        # Example environment config
│   └── logging.yaml               # Logging configuration
│
├── db/                            # Database artifacts
│   ├── migrations/                # Alembic migrations
│   │   ├── .gitkeep
│   │   └── 183c77cd21a4_initial_migration.py
│   └── schema.sql                 # Reference schema
│
├── docs/                          # Documentation and guides
│   ├── ruff-guide.md              # Linting & formatting
│   ├── mypy-guide.md              # Type checking
│   ├── pre-commit-guide.md        # Pre-commit hooks
│   └── deadcode-guide.md          # Dead code detection
│
├── pyproject.toml                 # Project config (updated for src/ + models/)
├── alembic.ini                    # Alembic configuration
├── mypy.ini                       # Type checking config
├── ruff.toml                      # Ruff linting config
├── .python-version                # Python version specification
├── .env.example                   # Template environment variables
├── .pre-commit-config.yaml        # Pre-commit hooks config
├── .gitignore
├── README.md
├── AGENTS.md
└── CLAUDE.md
```

---

## Dependency Graph

```
Zero-Dependency Types
├─ src/transactoid/models/transaction.py (Transaction, PersonalFinanceCategory)
└─ (no imports)

Domain Logic Layer (imports from models/)
├─ core/
│  ├─ errors.py (domain exceptions)
│  └─ [domain logic]
├─ taxonomy/
│  ├─ core.py (taxonomy logic, imports: core.errors, transactoid.models.*)
│  ├─ generator.py (loads YAML, imports: taxonomy.core)
│  └─ errors.py (taxonomy exceptions)
└─ (can import from: transactoid.models/)

Infrastructure Layer (imports from domain + models/)
├─ infra/
│  ├─ db/
│  │  └─ facade.py (imports: transactoid.models.transaction, core.*, taxonomy.*)
│  ├─ cache/
│  │  └─ file_cache.py (imports: transactoid.models.*)
│  ├─ clients/
│  │  ├─ plaid.py (imports: transactoid.models.transaction)
│  │  └─ plaid_link_flow.py
│  ├─ config.py (loads .env, YAML, imports: taxonomy.*)
│  └─ taxonomy_generator.py (deprecated, replaced by taxonomy.generator)
└─ (can import from: transactoid.models/, core/, taxonomy/)

Tool Implementations (imports from domain + infra + models/)
├─ tools/
│  ├─ base.py (tool protocol)
│  ├─ protocol.py (defines Tool interface)
│  ├─ registry.py (tool registry)
│  ├─ categorize/
│  │  └─ categorizer_tool.py (imports: models.transaction, taxonomy.*, infra.cache)
│  ├─ persist/
│  │  └─ persist_tool.py (imports: models.transaction, taxonomy.*, infra.db)
│  ├─ query/
│  │  └─ query_tool.py (imports: infra.db)
│  └─ sync/
│     └─ sync_tool.py (imports: models.transaction, taxonomy.*, infra.clients, tools.categorize)
└─ (can import from: models/, core/, taxonomy/, infra/)

Orchestration Layer (imports from tools + infra + domain + models/)
├─ orchestrators/
│  ├─ transactoid.py (agent loop, imports: all)
│  └─ openai_adapter.py (adapts tools to OpenAI SDK, imports: tools.protocol, tools.registry)
└─ (can import from: any except ui/)

UI Layer (imports from orchestrators + infra + models/)
├─ ui/
│  ├─ cli.py (imports: orchestrators.transactoid, infra.config, taxonomy.*)
│  ├─ simple_store.py
│  ├─ chatkit/
│  │  ├─ adapter.py (OpenAI Agent → ChatKit, imports: orchestrators.openai_adapter)
│  │  └─ server.py
│  └─ mcp/
│     ├─ adapter.py (OpenAI Agent → MCP, imports: orchestrators.openai_adapter)
│     └─ server.py
└─ (can import from: any except crossing back to orchestrators/infra/core/taxonomy/)

Scripts (imports from orchestrators + infra + models/)
├─ scripts/
│  ├─ run.py (imports: orchestrators.transactoid, infra.config)
│  ├─ plaid_cli.py (imports: infra.clients.plaid)
│  ├─ seed_taxonomy.py (imports: taxonomy.generator, infra.config)
│  ├─ build_taxonomy.py (imports: taxonomy.generator)
│  └─ migrate_legacy_categories.py (imports: infra.db)
└─ (can import from: any, not imported by anything)

Dependency Summary
═══════════════════════════════════════════════════════════════
  models/             → (nothing)
  ↑
  ├── core/           → models/
  ├── taxonomy/       → models/, core/
  │
  ├── infra/          → models/, core/, taxonomy/
  ├── tools/          → models/, core/, taxonomy/, infra/
  │
  ├── orchestrators/  → tools/, infra/, core/, models/
  │
  ├── ui/             → orchestrators/, infra/, models/
  │
  └── scripts/        → orchestrators/, infra/, models/

No Circular Dependencies ✓
```

### Phase 1: Consolidate UI
- [ ] Move all files from `frontends/` to `ui/`
- [ ] Update imports from `frontends.*` → `ui.*` throughout codebase
- [ ] Delete empty `frontends/` directory
- [ ] Update `pyproject.toml` `setuptools.packages.find.include` if needed

### Phase 2: Remove Dead Code
- [ ] Delete `tools/ingest/` directory and all subdirectories
- [ ] Delete `tests/tools/ingest/` directory (if exists)
- [ ] Remove ingest-related references from `pyproject.toml`
- [ ] Update README.md and CLAUDE.md to remove CSV ingestion plans

### Phase 3: Reorganize into `src/`
- [ ] Create `src/transactoid/` directory structure
- [ ] Move core packages to `src/transactoid/`:
  - `core/`, `infra/`, `tools/`, `prompts/`, `utils/`
- [ ] Create `src/transactoid/taxonomy/` subdomain:
  - Move `core/taxonomy.py` → `taxonomy/core.py`
  - Move `services/taxonomy_generator.py` → `taxonomy/generator.py`
  - Move taxonomy-specific exceptions to `taxonomy/errors.py`
- [ ] Create `src/transactoid/orchestrators/` with agent orchestration:
  - Move `orchestrators/transactoid.py` → `orchestrators/transactoid.py`
  - Move `adapters/openai_adapter.py` → `orchestrators/openai_adapter.py` (Tools → OpenAI format)
- [ ] Create `src/transactoid/ui/` with consolidated interfaces:
  - `cli.py`, `simple_store.py` from root `ui/` and `frontends/`
  - New `chatkit/` subpackage with `__init__.py`, `server.py`, and `chatkit_adapter.py` → `adapter.py`
  - New `mcp/` subpackage with `__init__.py`, `server.py`, and `mcp_adapter.py` → `adapter.py`
- [ ] Keep `models/` at root level with only `transaction.py` (no duplicate types in `src/`)
- [ ] Keep `tests/` at root, update test structure to match `src/` layout (including `tests/taxonomy/`, `tests/orchestrators/`)
- [ ] Delete empty `adapters/` and `frontends/` directories
- [ ] Update all internal imports: `from transactoid.taxonomy import Taxonomy` (not `from transactoid.core`)
- [ ] Update imports for openai_adapter: `from transactoid.orchestrators import openai_adapter`

### Phase 4: Update Configuration
- [ ] Update `pyproject.toml`:
  - Change `packages.find.include` to `["src/transactoid", "models"]`
  - Update entry point to `transactoid = "transactoid.ui.cli:agent"`
- [ ] Verify `alembic.ini` paths still valid
- [ ] Update any other config files that reference package paths

### Phase 5: Verify & Commit
- [ ] Run linter: `uv run ruff check .`
- [ ] Run formatter: `uv run ruff format .`
- [ ] Run type-checker: `uv run mypy --config-file mypy.ini .`
- [ ] Run dead code: `uv run deadcode .`
- [ ] Run tests: `uv run pytest -q`
- [ ] Commit as single change: `git commit -m "refactor: reorganize directory structure (src/, ui consolidation, remove ingest)"`

---

## Notes

- **No speculative files**: Only actual, used code is moved/organized
- **No duplicate types**: `models/transaction.py` is the single source of truth; not duplicated in `src/`
- **Taxonomy as subdomain**: Grouped together for cohesion (logic + generation + errors)
- **Import consistency**: Package name stays `transactoid` (already used everywhere); moving to `src/` is transparent
- **models/ at root**: Allows imports like `from models.transaction import Transaction` without importing from `src/`
- **tests/ at root**: Standard Python practice; mirrors `src/` structure for navigation
- **Dependency direction**: `models/ → core/ → taxonomy/` and `tools/infra` → all above
- **Future extensibility**: When CSV ingestion is needed, add `src/transactoid/tools/csv_ingest/` cleanly
- **Single commit**: All changes bundled together to avoid intermediate breakage
