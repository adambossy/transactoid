# Complete Directory Reorganization Strategy

## Overview

This document integrates the original REORGANIZATION_PLAN.md with the detailed services migration. It provides a complete, executable roadmap for reorganizing the entire project from current flat structure to `src/` with no circular dependencies.

---

## Phase 0: Pre-Migration Verification

Before starting, confirm the current state:

```bash
# Verify services/ exists with expected files
ls -la services/
# Expected: __init__.py, db.py, file_cache.py, plaid_client.py, plaid_link_flow.py, 
#           README.md, taxonomy.py, taxonomy_generator.py, yaml_utils.py

# Count import sites
grep -r "from services\." --include="*.py" | wc -l
# Expected: ~50+ occurrences

# Check for existing src/ conflicts
ls -la src/ 2>/dev/null || echo "src/ does not exist (good)"

# Verify current package setup
grep "packages.find.include" pyproject.toml
# Expected: include = ["agents*", "configs*", "db*", "models*", ...]
```

---

## Phase 1: Create Directory Structure

### Step 1.1: Create source tree

```bash
mkdir -p src/transactoid/{
  models,
  core,
  taxonomy,
  infrastructure/{db,cache,clients},
  tools,
  orchestrators,
  ui,
  prompts,
  utils
}

# Create __init__.py files
touch src/transactoid/__init__.py
touch src/transactoid/models/__init__.py
touch src/transactoid/core/__init__.py
touch src/transactoid/taxonomy/__init__.py
touch src/transactoid/infrastructure/__init__.py
touch src/transactoid/infrastructure/db/__init__.py
touch src/transactoid/infrastructure/cache/__init__.py
touch src/transactoid/infrastructure/clients/__init__.py
touch src/transactoid/tools/__init__.py
touch src/transactoid/orchestrators/__init__.py
touch src/transactoid/ui/__init__.py
touch src/transactoid/prompts/__init__.py
touch src/transactoid/utils/__init__.py
```

### Step 1.2: Verify structure

```bash
find src/transactoid -type f -name "__init__.py" | sort
# Should show all directories have __init__.py
```

---

## Phase 2: Migrate Services Layer (WITH CIRCULAR DEPENDENCY BREAK)

**Execution order matters**: Move from leaves to roots.

### Step 2.1: Migrate yaml_utils.py

```bash
cp services/yaml_utils.py src/transactoid/utils/yaml.py

# Verify (no dependencies)
grep "^from\|^import" src/transactoid/utils/yaml.py
# Should only show: yaml, typing, typing.Any, typing.cast
```

### Step 2.2: Migrate DB layer (SPLIT)

#### 2.2a: Extract ORM models from db.py

**Action**: Copy only model definitions to new file

```python
# Copy lines 1-210 (imports + models + types)
# File: src/transactoid/infrastructure/db/models.py
```

**Verify**:
```bash
python -c "from src.transactoid.infrastructure.db.models import DB" 2>&1 | grep -q "cannot import" && echo "GOOD: DB not in models.py"
python -c "from src.transactoid.infrastructure.db.models import Base" && echo "OK: Base imported"
```

#### 2.2b: Refactor DB class → facade.py

**Action**: Copy DB class with refactored `save_transactions()` method

```python
# File: src/transactoid/infrastructure/db/facade.py
# Key change: save_transactions() method signature
```

**Before**:
```python
def save_transactions(self, taxonomy: Taxonomy, txns):
    category_id = taxonomy.category_id_for_key(self, category_key)
```

**After**:
```python
def save_transactions(self, category_lookup: Callable[[str], int | None], txns):
    category_id = category_lookup(category_key)
```

**Verify**:
```bash
grep -n "Taxonomy" src/transactoid/infrastructure/db/facade.py
# Should have ZERO results

grep -n "category_lookup" src/transactoid/infrastructure/db/facade.py
# Should show: 1 in signature, 3+ in usage
```

### Step 2.3: Migrate Taxonomy (SPLIT)

#### 2.3a: Extract pure domain logic

```bash
cp services/taxonomy.py src/transactoid/taxonomy/core.py

# Edit core.py: REMOVE these lines
# - Line 6: from services.db import DB
# - Lines 32-55: @classmethod def from_db()
# - Lines 86-87: def category_id_for_key()

# Keep from_nodes() classmethod
```

**Verify**:
```bash
grep "from services" src/transactoid/taxonomy/core.py
# Should have ZERO results

python -c "from src.transactoid.taxonomy.core import Taxonomy; print('OK')"
# Should succeed without DB import
```

#### 2.3b: Create loader module (NEW FILE)

```python
# File: src/transactoid/taxonomy/loader.py
# Contents: load_taxonomy_from_db(), get_category_id()
# (See SERVICES_MIGRATION_REFERENCE.md for full code)
```

**Verify**:
```bash
python -c "from src.transactoid.taxonomy.loader import load_taxonomy_from_db; print('OK')"
```

### Step 2.4: Migrate other services

```bash
cp services/plaid_link_flow.py src/transactoid/infrastructure/clients/plaid_link.py
cp services/plaid_client.py src/transactoid/infrastructure/clients/plaid.py
cp services/file_cache.py src/transactoid/infrastructure/cache/file_cache.py
cp services/taxonomy_generator.py src/transactoid/taxonomy/generator.py
```

**Update imports in each file**:
- `services.yaml_utils` → `src.transactoid.utils.yaml`
- `services.plaid_link_flow` → `src.transactoid.infrastructure.clients.plaid_link`
- `services.db` → `src.transactoid.infrastructure.db.facade` (plaid_client.py)

---

## Phase 3: Migrate Core Packages (EXISTING, MOVE TO SRC)

### Step 3.1: Move infrastructure layers

```bash
# Models layer
cp -r models src/transactoid/

# Core layer (if exists separately)
cp -r core src/transactoid/ 2>/dev/null || echo "core/ may not exist as separate dir"

# Tools layer
cp -r tools src/transactoid/

# Prompts layer
cp -r prompts src/transactoid/ 2>/dev/null || echo "prompts/ may not exist at root"
```

### Step 3.2: Move orchestration

```bash
cp -r orchestrators src/transactoid/

# Move openai_adapter into orchestrators
cp adapters/openai_adapter.py src/transactoid/orchestrators/openai_adapter.py
```

### Step 3.3: Consolidate UI layers (WITH ADAPTER REORGANIZATION)

```bash
# Move existing UI files
cp ui/cli.py src/transactoid/ui/
cp ui/simple_store.py src/transactoid/ui/ 2>/dev/null || echo "simple_store may not exist"

# Move frontends → ui (with reorganization)
cp frontends/chatkit_server.py src/transactoid/ui/chatkit/server.py
cp adapters/chatkit_adapter.py src/transactoid/ui/chatkit/adapter.py

cp frontends/mcp_server.py src/transactoid/ui/mcp/server.py
cp adapters/mcp_adapter.py src/transactoid/ui/mcp/adapter.py

cp frontends/simple_store.py src/transactoid/ui/simple_store.py 2>/dev/null

# Create __init__.py for UI subpackages
touch src/transactoid/ui/chatkit/__init__.py
touch src/transactoid/ui/mcp/__init__.py
```

---

## Phase 4: Update All Imports (32+ Files)

### Step 4.1: Generate import replacement script

```bash
# Create script to update imports (run in project root)
cat > /tmp/update_imports.sh << 'EOF'
#!/bin/bash

# Define replacements
declare -A REPLACEMENTS=(
    ["from services.db import"]="from src.transactoid.infrastructure.db.facade import"
    ["from services.taxonomy import"]="from src.transactoid.taxonomy.core import"
    ["from services.file_cache import"]="from src.transactoid.infrastructure.cache.file_cache import"
    ["from services.plaid_client import"]="from src.transactoid.infrastructure.clients.plaid import"
    ["from services.plaid_link_flow import"]="from src.transactoid.infrastructure.clients.plaid_link import"
    ["from services.yaml_utils import"]="from src.transactoid.utils.yaml import"
    ["from services import taxonomy_generator"]="from src.transactoid.taxonomy import generator"
    ["from services.taxonomy_generator import"]="from src.transactoid.taxonomy.generator import"
    ["from adapters.openai_adapter import"]="from src.transactoid.orchestrators.openai_adapter import"
    ["from adapters.chatkit_adapter import"]="from src.transactoid.ui.chatkit.adapter import"
    ["from adapters.mcp_adapter import"]="from src.transactoid.ui.mcp.adapter import"
    ["from frontends.chatkit_server import"]="from src.transactoid.ui.chatkit.server import"
    ["from frontends.mcp_server import"]="from src.transactoid.ui.mcp.server import"
    ["from frontends.simple_store import"]="from src.transactoid.ui.simple_store import"
    ["from ui.cli import"]="from src.transactoid.ui.cli import"
    ["from orchestrators."]="from src.transactoid.orchestrators."
    ["from tools."]="from src.transactoid.tools."
    ["from models."]="from src.transactoid.models."
)

# Files to update
FILES=$(find . -type f -name "*.py" -not -path "./.*" -not -path "./.venv/*" -not -path "./src/transactoid/*")

for file in $FILES; do
    for old in "${!REPLACEMENTS[@]}"; do
        new="${REPLACEMENTS[$old]}"
        sed -i "s|$old|$new|g" "$file"
    done
done

echo "Import updates complete"
EOF

chmod +x /tmp/update_imports.sh
/tmp/update_imports.sh
```

### Step 4.2: Manually verify critical files

```bash
# Check that main entry point is correct
grep "^transactoid = " pyproject.toml
# Current: transactoid = "ui.cli:agent"
# Should become: transactoid = "transactoid.ui.cli:agent"
```

### Step 4.3: Manual fixes (special cases)

**alembic/env.py**:
```python
# Before
from services.db import Base

# After
from src.transactoid.infrastructure.db.models import Base
```

**Scripts that use Taxonomy + DB together**:
```python
# Before
from services.db import DB
from services.taxonomy import Taxonomy

db = DB(url)
taxonomy = Taxonomy.from_db(db)

# After
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.taxonomy.loader import load_taxonomy_from_db

db = DB(url)
taxonomy = load_taxonomy_from_db(db)
```

**Tools that call save_transactions**:
```python
# Before
outcome = db.save_transactions(taxonomy, txns)

# After
from src.transactoid.taxonomy.loader import get_category_id
category_lookup = lambda key: get_category_id(db, taxonomy, key)
outcome = db.save_transactions(category_lookup, txns)
```

---

## Phase 5: Update Configuration

### Step 5.1: Update pyproject.toml

```toml
[project.scripts]
transactoid = "transactoid.ui.cli:agent"

[tool.setuptools.packages.find]
include = ["src/transactoid", "models"]
where = ["src", "."]
```

### Step 5.2: Verify Python path

```bash
# Ensure imports work from project root
python -c "from src.transactoid.taxonomy.core import Taxonomy; print('OK')"
python -c "from src.transactoid.infrastructure.db.facade import DB; print('OK')"
```

---

## Phase 6: Consolidate UI (FROM ORIGINAL PLAN)

### Step 6.1: Remove dead adapter files

```bash
# These are now in src/transactoid/ui/
rm -f adapters/openai_adapter.py
rm -f adapters/chatkit_adapter.py
rm -f adapters/mcp_adapter.py

# Remove empty directories
rmdir adapters/ 2>/dev/null
rm -rf frontends/
```

### Step 6.2: Verify UI structure

```bash
find src/transactoid/ui -type f -name "*.py" | sort

# Expected:
# src/transactoid/ui/__init__.py
# src/transactoid/ui/cli.py
# src/transactoid/ui/simple_store.py
# src/transactoid/ui/chatkit/__init__.py
# src/transactoid/ui/chatkit/adapter.py
# src/transactoid/ui/chatkit/server.py
# src/transactoid/ui/mcp/__init__.py
# src/transactoid/ui/mcp/adapter.py
# src/transactoid/ui/mcp/server.py
```

---

## Phase 7: Remove Dead Code (FROM ORIGINAL PLAN)

### Step 7.1: Remove ingest directory

```bash
rm -rf tools/ingest/
rm -rf tests/tools/ingest/
```

### Step 7.2: Update documentation

Edit README.md and CLAUDE.md:
- Remove references to "planned CSV ingestion"
- Update to reflect that Plaid sync is the only ingestion mechanism

---

## Phase 8: Delete Old Root-Level Directories

```bash
# Verify all moved to src/ before deleting
find src/transactoid -type f -name "*.py" | wc -l
# Should be >100 files

# Remove old root directories (after verifying copies exist)
rm -rf services/
rm -rf ui/  # OLD ui, not the one in src/transactoid/ui/
rm -rf adapters/
rm -rf frontends/
rm -rf tools/  # ONLY IF all files moved to src/transactoid/tools/
rm -rf orchestrators/  # ONLY IF all files moved
rm -rf prompts/ 2>/dev/null
rm -rf core/ 2>/dev/null
```

**CAUTION**: Before deleting, verify with:
```bash
diff -r tools/ src/transactoid/tools/
diff -r orchestrators/ src/transactoid/orchestrators/
# Should show no differences (or expected renames)
```

---

## Phase 9: Verification & Testing

### Step 9.1: Syntax and import checks

```bash
# Type checking
uv run mypy --config-file mypy.ini src/ tests/

# Linting
uv run ruff check src/ tests/ scripts/

# Formatting
uv run ruff format --check src/ tests/ scripts/

# Dead code
uv run deadcode src/
```

### Step 9.2: Runtime checks

```bash
# Can import all main modules
python -c "
from src.transactoid.taxonomy.core import Taxonomy
from src.transactoid.taxonomy.loader import load_taxonomy_from_db
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.infrastructure.db.models import Base
from src.transactoid.infrastructure.clients.plaid import PlaidClient
from src.transactoid.infrastructure.cache.file_cache import FileCache
from src.transactoid.orchestrators.transactoid import Transactoid
from src.transactoid.ui.cli import app
print('All imports OK')
"

# Can run tests
uv run pytest tests/ -v

# Can run CLI
python -m transactoid --help
```

### Step 9.3: Specific circular import checks

```bash
# Verify no cycles
python << 'EOF'
import sys
import importlib

modules_to_check = [
    'src.transactoid.taxonomy.core',
    'src.transactoid.taxonomy.loader',
    'src.transactoid.infrastructure.db.facade',
    'src.transactoid.infrastructure.db.models',
]

for module_name in modules_to_check:
    try:
        importlib.import_module(module_name)
        print(f"✓ {module_name}")
    except ImportError as e:
        print(f"✗ {module_name}: {e}")
        sys.exit(1)

print("\nNo circular imports detected!")
EOF
```

---

## Phase 10: Update Test Structure (MIRRORS SRC)

### Step 10.1: Reorganize tests

```bash
# Move test directories to match src/ structure
mkdir -p tests/{core,taxonomy,infrastructure/{db,cache,clients},tools,orchestrators,ui}

# Move test files
mv tests/services/test_taxonomy.py tests/taxonomy/test_core.py
mv tests/services/test_db.py tests/infrastructure/db/test_facade.py
mv tests/services/test_file_cache.py tests/infrastructure/cache/test_file_cache.py
mv tests/services/ tests/infrastructure/ (if applicable)
```

### Step 10.2: Update test imports

Same import replacements as source files.

---

## Phase 11: Final Cleanup

### Step 11.1: Remove migration artifacts

```bash
rm -f REORGANIZATION_PLAN.md
rm -f SERVICES_MIGRATION_PLAN.md
rm -f SERVICES_MIGRATION_REFERENCE.md
rm -f CIRCULAR_DEPENDENCY_SOLUTION.md
rm -f COMPLETE_REORGANIZATION_STRATEGY.md

# Or archive them:
mkdir -p .archived_docs
mv REORGANIZATION_PLAN.md SERVICES_MIGRATION_PLAN.md ... .archived_docs/
```

### Step 11.2: Verify no old imports remain

```bash
# Should have zero results
grep -r "from services\." --include="*.py" .
grep -r "import services" --include="*.py" .
grep -r "from adapters" --include="*.py" . | grep -v ".archived"
grep -r "from frontends" --include="*.py" . | grep -v ".archived"
```

### Step 11.3: Commit

```bash
git add -A
git commit -m "refactor: reorganize directory structure

- Create src/transactoid/ with all source code
- Split services/ into infrastructure/, taxonomy/, utils/
- Break Taxonomy↔DB circular dependency with loader module
- Consolidate UI: merge frontends/ + adapters/ into ui/
- Update 40+ import paths
- Remove dead code (tools/ingest/)
- Update pyproject.toml for src/ layout"
```

---

## Execution Time Estimate

| Phase | Task | Time |
|-------|------|------|
| 0 | Pre-migration checks | 10 min |
| 1 | Create directory structure | 10 min |
| 2 | Migrate services/ (with split & refactor) | 60 min |
| 3 | Move core packages | 20 min |
| 4 | Update 40+ import sites | 90 min |
| 5 | Update configuration | 15 min |
| 6 | Consolidate UI | 15 min |
| 7 | Remove dead code | 5 min |
| 8 | Delete old directories | 10 min |
| 9 | Verification & testing | 60 min |
| 10 | Reorganize tests | 30 min |
| 11 | Final cleanup & commit | 15 min |
| **Total** | | **4-5 hours** |

---

## Rollback Plan

If issues arise during migration:

```bash
# Restore from backup (created before Phase 1)
git checkout HEAD -- .

# Or restore specific directories
git checkout HEAD -- services/
git checkout HEAD -- ui/
git checkout HEAD -- adapters/
```

---

## Post-Migration Benefits

✓ Clear separation: source vs. tests vs. config  
✓ No circular imports (Taxonomy ↔ DB resolved)  
✓ Follows Python packaging standards  
✓ Easier to add new domains (e.g., CSV ingestion)  
✓ Better testability (domain logic decoupled from infra)  
✓ Single source of truth for types (models/)  
✓ Clear dependency direction (tools → infra → core → models)  

