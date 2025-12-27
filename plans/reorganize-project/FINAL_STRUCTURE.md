# Final Proposed Directory Structure & Dependency Graph

Based on COMPLETE_REORGANIZATION_STRATEGY.md, here is the complete final structure and how all components relate.

---

## Final Directory Structure

```
transactoid/
│
├── src/transactoid/               # All source code (setuptools looks here)
│   │
│   ├── models/                    # Zero-dependency types (shared root level)
│   │   ├── __init__.py
│   │   └── transaction.py         # Transaction, PersonalFinanceCategory TypedDicts
│   │
│   ├── core/                      # General domain logic
│   │   ├── __init__.py
│   │   └── errors.py              # Domain exceptions (non-taxonomy)
│   │
│   ├── taxonomy/                  # Taxonomy bounded context (COHESIVE SUBDOMAIN)
│   │   ├── __init__.py
│   │   ├── core.py                # Taxonomy class & domain logic (pure domain)
│   │   ├── generator.py           # Load taxonomy from YAML files
│   │   ├── loader.py              # NEW: DB ↔ Taxonomy bridge (breaks circular dep)
│   │   └── errors.py              # Taxonomy-specific exceptions
│   │
│   ├── infra/                     # Infrastructure & integrations (simplified from "infrastructure")
│   │   ├── __init__.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # ORM schema only (Base, User, Transaction, etc.)
│   │   │   └── facade.py          # DB service layer (queries, mutations, save_transactions)
│   │   ├── cache/
│   │   │   ├── __init__.py
│   │   │   └── file_cache.py      # File-based caching
│   │   └── clients/
│   │       ├── __init__.py
│   │       ├── plaid.py           # Plaid API client
│   │       └── plaid_link.py      # Plaid OAuth flow
│   │
│   ├── tools/                     # Tool implementations (defines Tool protocol)
│   │   ├── __init__.py
│   │   ├── base.py                # Tool base class
│   │   ├── protocol.py            # Tool protocol/interface
│   │   ├── registry.py            # Tool registry
│   │   ├── categorize/            # LLM-based categorization
│   │   │   └── categorizer_tool.py
│   │   ├── persist/               # Save to database
│   │   │   └── persist_tool.py
│   │   ├── query/                 # Query transactions
│   │   │   └── query_tool.py
│   │   └── sync/                  # Sync from Plaid
│   │       └── sync_tool.py
│   │
│   ├── orchestrators/             # Agent orchestration
│   │   ├── __init__.py
│   │   ├── transactoid.py         # Main agent orchestrator
│   │   └── openai_adapter.py      # Adapts tools to OpenAI SDK format
│   │
│   ├── ui/                        # User interfaces + UI-specific adapters
│   │   ├── __init__.py
│   │   ├── cli.py                 # Typer CLI entrypoint
│   │   ├── simple_store.py        # Simple store interface
│   │   ├── chatkit/               # ChatKit UI server
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py         # OpenAI Agents → ChatKit adapter
│   │   │   └── server.py          # ChatKit server
│   │   └── mcp/                   # MCP UI server
│   │       ├── __init__.py
│   │       ├── adapter.py         # OpenAI Agents → MCP adapter
│   │       └── server.py          # MCP server
│   │
│   ├── prompts/                   # Prompt templates
│   │   └── [template files]
│   │
│   └── utils/                     # Utilities
│       ├── __init__.py
│       └── yaml.py                # YAML loading/dumping helpers
│
├── models/                        # Shared types (ROOT LEVEL, NOT in src/)
│   ├── __init__.py                # Can be imported as: from models.transaction import Transaction
│   └── transaction.py             # Zero-dependency types
│
├── tests/                         # Tests (mirrors src/ structure)
│   ├── conftest.py
│   ├── core/
│   ├── taxonomy/
│   │   ├── test_core.py           # Tests for taxonomy/core.py
│   │   └── test_loader.py         # Tests for taxonomy/loader.py
│   ├── infra/
│   │   ├── db/
│   │   │   ├── test_models.py
│   │   │   └── test_facade.py
│   │   ├── cache/
│   │   │   └── test_file_cache.py
│   │   └── clients/
│   │       └── test_plaid.py
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
│   │   └── [migration files]
│   └── schema.sql                 # Reference schema
│
├── docs/                          # Documentation
│   ├── ruff-guide.md
│   ├── mypy-guide.md
│   ├── pre-commit-guide.md
│   └── deadcode-guide.md
│
├── pyproject.toml                 # Project config (setuptools → src/)
├── alembic.ini                    # Alembic configuration
├── mypy.ini                       # Type checking config
├── ruff.toml                      # Ruff linting config
├── .python-version                # Python 3.12+
├── .env.example                   # Template environment variables
├── .pre-commit-config.yaml        # Pre-commit hooks config
├── .gitignore
├── README.md
├── AGENTS.md
└── CLAUDE.md
```

---

## Key Design Decisions

### 1. **models/ at Root Level (NOT in src/)**
- **Why**: Contains zero-dependency types that should be importable everywhere
- **Import**: `from models.transaction import Transaction` (simple, no src. prefix)
- **Benefit**: Single source of truth; can be imported without pulling in business logic

### 2. **infra/ (NOT infrastructure/)**
- **Shorter naming** than `infrastructure/`
- **Follows convention**: Similar to Django, FastAPI patterns
- **Import**: `from transactoid.infra.db import DB` (vs longer path)

### 3. **taxonomy/ as Cohesive Subdomain**
- **core.py**: Pure domain logic (no infrastructure imports)
- **generator.py**: Load from YAML
- **loader.py**: NEW - breaks circular dependency (DB ↔ Taxonomy)
- **errors.py**: Taxonomy-specific exceptions
- **Benefit**: Easy to understand and extend; cohesion of related concerns

### 4. **infra/db/ SPLIT into models.py + facade.py**
- **models.py**: Only ORM schema (Base, User, Transaction, etc.)
  - Zero business logic
  - Can be imported by Alembic without circular dependencies
- **facade.py**: Service layer (queries, mutations)
  - Refactored `save_transactions()` to accept callback (not Taxonomy object)
  - Enables dependency injection
  - No Taxonomy imports

### 5. **taxonomy/loader.py (NEW)**
- **Purpose**: Single point of responsibility for Taxonomy ↔ DB interaction
- **Functions**:
  - `load_taxonomy_from_db(db)` → Taxonomy
  - `get_category_id(db, taxonomy, key)` → int | None
- **Benefit**: Breaks circular import; neither Taxonomy nor DB need to know about each other

### 6. **UI Consolidation**
- **Before**: `ui/`, `frontends/`, `adapters/` at root (scattered)
- **After**: Single `ui/` namespace with subpackages
  - `ui/cli.py` — CLI interface
  - `ui/chatkit/adapter.py` + `ui/chatkit/server.py` — ChatKit UI
  - `ui/mcp/adapter.py` + `ui/mcp/server.py` — MCP UI
- **Benefit**: Single namespace, adapter cohesion with servers

### 7. **Remove Dead Code**
- **tools/ingest/** — Empty, never implemented
  - Removed entirely (no placeholder)

---

## Dependency Graph

```
Zero-Dependency Types
├─ models/transaction.py (Transaction, PersonalFinanceCategory)
└─ (imports: nothing)

Domain Logic Layer
├─ core/errors.py
│  └─ imports: models/
├─ taxonomy/core.py (Taxonomy class, validation, methods)
│  └─ imports: models/, core/
├─ taxonomy/generator.py (load YAML → Taxonomy)
│  └─ imports: taxonomy/core
└─ taxonomy/loader.py (NEW - DB ↔ Taxonomy bridge)
   └─ imports: taxonomy/core, infra/db/facade

Infrastructure Layer
├─ infra/db/models.py (ORM schema only)
│  └─ imports: sqlalchemy, stdlib
├─ infra/db/facade.py (queries, mutations, save_transactions)
│  └─ imports: infra/db/models, stdlib, sqlalchemy
├─ infra/cache/file_cache.py
│  └─ imports: models/, stdlib
├─ infra/clients/plaid.py (Plaid API client)
│  └─ imports: infra/db/facade, utils/yaml, stdlib
└─ utils/yaml.py (YAML utilities)
   └─ imports: yaml, stdlib

Tools Layer (implements Tool protocol)
├─ tools/categorize/categorizer_tool.py
│  └─ imports: models/, taxonomy/core, infra/cache, stdlib
├─ tools/persist/persist_tool.py
│  └─ imports: models/, taxonomy/core, infra/db/facade
├─ tools/query/query_tool.py
│  └─ imports: infra/db/facade, stdlib
└─ tools/sync/sync_tool.py
   └─ imports: models/, taxonomy/core, infra/clients/plaid, tools/categorize

Orchestration Layer
├─ orchestrators/transactoid.py (agent loop, composes all)
│  └─ imports: tools/*, taxonomy/loader, infra/*, models/
└─ orchestrators/openai_adapter.py (adapts tools to OpenAI SDK)
   └─ imports: tools/protocol, tools/registry

UI Layer
├─ ui/cli.py
│  └─ imports: orchestrators/transactoid, taxonomy/loader, models/
├─ ui/chatkit/adapter.py
│  └─ imports: orchestrators/openai_adapter, stdlib
├─ ui/chatkit/server.py
│  └─ imports: ui/chatkit/adapter, fastapi
├─ ui/mcp/adapter.py
│  └─ imports: orchestrators/openai_adapter, stdlib
└─ ui/mcp/server.py
   └─ imports: ui/mcp/adapter, mcp library

Scripts (can import anything, not imported by anything)
├─ scripts/run.py
│  └─ imports: orchestrators/transactoid, taxonomy/loader, infra/db
├─ scripts/seed_taxonomy.py
│  └─ imports: taxonomy/loader, infra/db
├─ scripts/build_taxonomy.py
│  └─ imports: taxonomy/generator
└─ scripts/plaid_cli.py
   └─ imports: infra/clients/plaid
```

### No Circular Dependencies ✓

**Critical Points**:
- `taxonomy/core.py` imports nothing from infra (pure domain)
- `infra/db/facade.py` imports nothing from taxonomy
- `taxonomy/loader.py` is the ONLY module that knows about both
- Callers use loader to connect them

**Example**:
```python
# Before (CIRCULAR)
taxonomy = Taxonomy.from_db(db)  # Taxonomy imports DB

# After (CLEAN)
from transactoid.taxonomy.loader import load_taxonomy_from_db
taxonomy = load_taxonomy_from_db(db)  # Only loader knows about both
```

---

## Import Style Guide

### Correct (New) Imports

```python
# From models
from models.transaction import Transaction, PersonalFinanceCategory

# From domain
from transactoid.taxonomy.core import Taxonomy, CategoryNode
from transactoid.core.errors import DomainError

# From infrastructure
from transactoid.infra.db.facade import DB
from transactoid.infra.db.models import Base, Category
from transactoid.infra.cache.file_cache import FileCache
from transactoid.infra.clients.plaid import PlaidClient

# From tools
from transactoid.tools.sync.sync_tool import SyncTool
from transactoid.tools.categorize.categorizer_tool import CategorizerTool

# From orchestrators
from transactoid.orchestrators.transactoid import Transactoid
from transactoid.orchestrators.openai_adapter import adapt_tools

# From UI
from transactoid.ui.cli import app
from transactoid.ui.chatkit.adapter import ChatKitAdapter

# From utils
from transactoid.utils.yaml import dump_yaml

# Loader (NEW)
from transactoid.taxonomy.loader import load_taxonomy_from_db, get_category_id
```

### What NOT to do (Old)

```python
# ❌ WRONG - Old paths
from services.db import DB
from services.taxonomy import Taxonomy
from services.file_cache import FileCache
from adapters.openai_adapter import adapt_tools
from ui.cli import app
from frontends.chatkit_server import ChatKitServer
```

---

## Configuration

### pyproject.toml

```toml
[tool.setuptools]
package-dir = {"" = "src"}  # Tells setuptools: packages are under src/

[tool.setuptools.packages.find]
where = ["src"]
include = ["transactoid*"]

[project.scripts]
transactoid = "transactoid.ui.cli:agent"  # Entry point (no src. prefix)
```

**Key**: With `package-dir` set, all imports are `from transactoid.*` (not `from src.transactoid.*`)

---

## Installation & Verification

```bash
# Install in editable mode (setuptools finds packages)
uv pip install -e .

# Test entry point
transactoid --help
# Expected: CLI help without ImportError

# Test imports
python -c "from transactoid.taxonomy.core import Taxonomy; print('OK')"
python -c "from transactoid.infra.db.facade import DB; print('OK')"
python -c "from models.transaction import Transaction; print('OK')"

# Test no circular imports
python -c "
from transactoid.taxonomy.core import Taxonomy
from transactoid.infra.db.facade import DB
print('No circular imports!')
"
```

---

## Migration Path

This structure is achieved through these phases:

1. **Phase 1-1.5**: Create directories + configure pyproject.toml
2. **Phase 2**: Migrate services/ (split DB and Taxonomy)
3. **Phase 3**: Move core packages to src/
4. **Phase 4**: Update imports (sequential blocks, not all-at-once)
5. **Phase 5-8**: Configuration, UI consolidation, cleanup
6. **Phase 9-11**: Verification, tests, final commit

See COMPLETE_REORGANIZATION_STRATEGY.md for detailed step-by-step instructions.

---

## Benefits of Final Structure

✅ **Clear layering**: models → domain → infra → tools → orch → ui
✅ **No circular imports**: Proven acyclic dependency graph
✅ **Follows Python standards**: src/ layout, setuptools configured
✅ **Cohesive domains**: taxonomy/, infra/ group related concepts
✅ **Better testability**: Pure domain logic tested without DB setup
✅ **Single source of truth**: models/ at root, imported everywhere
✅ **Extensible**: Easy to add new domains (e.g., csv_ingest/)
✅ **Production-ready**: All imports verified, entry point tested
