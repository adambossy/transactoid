# Complete Directory Reorganization Strategy

## Overview

This document provides a complete, executable roadmap for reorganizing the entire project from current flat structure to `src/` with no circular dependencies. It integrates the original REORGANIZATION_PLAN.md with detailed services migration and addresses critical configuration issues.

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

# Verify Python version
python --version
# Expected: 3.12+
```

---

## Important: Execution Strategy

**Do not move all files then update imports.** This creates a broken state where both old and new paths exist, masking import errors.

Instead, use **sequential blocks**: Move and fix one functional area at a time, running tests before moving to the next area. This keeps the codebase working throughout the migration.

---

## Phase 1: Create Directory Structure

### Step 1.1: Create source tree

```bash
mkdir -p src/transactoid/{
  models,
  core,
  taxonomy,
  infra/{db,cache,clients},
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
touch src/transactoid/infra/__init__.py
touch src/transactoid/infra/db/__init__.py
touch src/transactoid/infra/cache/__init__.py
touch src/transactoid/infra/clients/__init__.py
touch src/transactoid/tools/__init__.py
touch src/transactoid/orchestrators/__init__.py
touch src/transactoid/ui/__init__.py
touch src/transactoid/prompts/__init__.py
touch src/transactoid/utils/__init__.py
```

### Step 1.2: Verify structure

```bash
find src/transactoid -type f -name "__init__.py" | sort
# Should show all directories have __init__.py (12 total)
```

---

## Phase 1.5: Update pyproject.toml (CRITICAL - DO THIS BEFORE PHASE 2)

This must be done **before** moving files to ensure imports resolve correctly.

```toml
# pyproject.toml

[build-system]
requires = ["setuptools>=65", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "transactoid"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    # ... unchanged ...
]

[project.scripts]
transactoid = "transactoid.ui.cli:agent"  # ← UPDATED: removed "ui." prefix

[tool.setuptools]
package-dir = {"" = "src"}  # ← ADDED: tells setuptools to look in src/

[tool.setuptools.packages.find]
where = ["src"]  # ← ADDED: search for packages under src/
include = ["transactoid*"]  # ← CHANGED: simpler pattern

# models/ is a separate root-level package (zero-dependency types)
# It's NOT under src/ to keep imports simple: from models.transaction import Transaction
```

Verify the configuration:
```bash
cd /path/to/project

# Check setuptools recognizes the new structure
python -c "import setuptools; print('setuptools OK')"

# Install in development mode (important!)
uv pip install -e .
# or: pip install -e .

# Verify the entry point works
transactoid --help
# Expected: Shows CLI help without errors

# Verify imports work
python -c "
from transactoid.taxonomy.core import Taxonomy
from transactoid.infra.db.facade import DB
print('✓ All imports resolve correctly')
"
```

If any step fails, you have a pyproject.toml configuration issue. **Fix it before proceeding to Phase 2.**

---

## Phase 2: Migrate Services Layer (WITH CIRCULAR DEPENDENCY BREAK)

**Execution order matters**: Move from leaves to roots.

### Step 2.1: Migrate yaml_utils.py (LEAVES FIRST)

```bash
cp services/yaml_utils.py src/transactoid/utils/yaml.py

# Verify (no dependencies)
grep "^from\|^import" src/transactoid/utils/yaml.py
# Should only show: yaml, typing, typing.Any, typing.cast

# Verify import works
python -c "from transactoid.utils.yaml import dump_yaml; print('✓ yaml imports OK')"
```

### Step 2.2: Migrate DB layer (SPLIT)

#### 2.2a: Extract ORM models from db.py

**Action**: Copy only model definitions to new file

```python
# Copy lines 1-210 (imports + models + types)
# File: src/transactoid/infra/db/models.py
```

**Verify**:
```bash
python -c "from transactoid.infra.db.models import DB" 2>&1 | grep -q "cannot import" && echo "GOOD: DB not in models.py"
python -c "from transactoid.infra.db.models import Base" && echo "✓ Base imported"
```

#### 2.2b: Refactor DB class → facade.py

**Action**: Copy DB class with refactored `save_transactions()` method

```python
# File: src/transactoid/infra/db/facade.py
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
grep -n "Taxonomy" src/transactoid/infra/db/facade.py
# Should have ZERO results

grep -n "category_lookup" src/transactoid/infra/db/facade.py
# Should show: 1 in signature, 3+ in usage

python -c "from transactoid.infra.db.facade import DB; print('✓ DB facade imports OK')"
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

python -c "from transactoid.taxonomy.core import Taxonomy; print('✓ Taxonomy core imports OK')"
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
python -c "from transactoid.taxonomy.loader import load_taxonomy_from_db; print('✓ Taxonomy loader imports OK')"
```

### Step 2.4: Migrate other services

```bash
cp services/plaid_link_flow.py src/transactoid/infra/clients/plaid_link.py
cp services/plaid_client.py src/transactoid/infra/clients/plaid.py
cp services/file_cache.py src/transactoid/infra/cache/file_cache.py
cp services/taxonomy_generator.py src/transactoid/taxonomy/generator.py
```

**Update imports in each file**:
- `services.yaml_utils` → `transactoid.utils.yaml`
- `services.plaid_link_flow` → `transactoid.infra.clients.plaid_link`
- `services.db` → `transactoid.infra.db.facade` (plaid_client.py)

**Verify** (after updating imports):
```bash
python -c "from transactoid.infra.clients.plaid import PlaidClient; print('✓ Plaid client imports OK')"
python -c "from transactoid.infra.cache.file_cache import FileCache; print('✓ Cache imports OK')"
python -c "from transactoid.taxonomy.generator import TaxonomyGenerator; print('✓ Taxonomy generator imports OK')"
```

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
# Create subdirectories
mkdir -p src/transactoid/ui/chatkit
mkdir -p src/transactoid/ui/mcp

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

# Update imports in these files from services.* and adapters.* to transactoid.*
# Key replacements:
#   - services.db → transactoid.infra.db.facade
#   - services.taxonomy → transactoid.taxonomy.core
#   - services (any) → transactoid.infra.* or transactoid.taxonomy.*
```

---

## Phase 4: Update All Imports (32+ Files) — SEQUENTIAL BLOCKS

**CRITICAL**: Do NOT move all files then fix imports. Use **sequential blocks** to keep tests passing at each step.

### Step 4.1: DB layer imports (after Phase 2 DB migration)

```bash
# Update files importing from services.db
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.db import/from transactoid.infra.db.facade import/g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.db import/from transactoid.infra.db.models import/g' {} \;

# Test DB-related tests
uv run pytest tests/infra/db/ -v 2>&1 || echo "⚠ DB tests may have import errors; fix manually"

# Verify no old DB imports remain in source
grep -r "from services.db" --include="*.py" src/ tests/ scripts/ || echo "✓ No old DB imports"
```

### Step 4.2: Taxonomy imports (after Phase 2 Taxonomy migration)

```bash
# Update taxonomy imports
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.taxonomy import/from transactoid.taxonomy.core import/g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.taxonomy_generator/from transactoid.taxonomy.generator/g' {} \;

# Replace Taxonomy.from_db() calls with loader
# This requires MANUAL updates — see SERVICES_MIGRATION_REFERENCE.md for patterns

# Test taxonomy
uv run pytest tests/taxonomy/ -v 2>&1 || echo "⚠ Taxonomy tests may have errors; check Taxonomy.from_db() usage"

# Verify
grep -r "from services.taxonomy" --include="*.py" src/ tests/ scripts/ || echo "✓ No old taxonomy imports"
```

### Step 4.3: Infrastructure (cache, clients) imports

```bash
# Cache
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.file_cache/from transactoid.infra.cache.file_cache/g' {} \;

# Plaid client
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.plaid_client/from transactoid.infra.clients.plaid/g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.plaid_link_flow/from transactoid.infra.clients.plaid_link/g' {} \;

# YAML utils
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from services\.yaml_utils/from transactoid.utils.yaml/g' {} \;

# Test infra
uv run pytest tests/infra/ -v 2>&1 || echo "⚠ Infra tests may have errors"

# Verify
grep -r "from services\.\(file_cache\|plaid_\|yaml_utils\)" --include="*.py" src/ tests/ scripts/ \
  || echo "✓ No old infra imports"
```

### Step 4.4: Top-level packages (orchestrators, tools, ui, models)

```bash
# Orchestrators
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from orchestrators\./from transactoid.orchestrators./g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from adapters\.openai_adapter/from transactoid.orchestrators.openai_adapter/g' {} \;

# Tools
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from tools\./from transactoid.tools./g' {} \;

# UI (new paths)
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from ui\.cli/from transactoid.ui.cli/g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from adapters\.\(chatkit\|mcp\)_adapter/from transactoid.ui.\1.adapter/g' {} \;

find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from frontends\.\(chatkit\|mcp\)_server/from transactoid.ui.\1.server/g' {} \;

# Models
find src tests scripts -name "*.py" -type f -exec sed -i \
  's/from models\./from transactoid.models./g' {} \;

# Test everything
uv run pytest tests/ -v

# Verify no old imports in source
for pattern in "from services\." "from adapters\." "from frontends\." "from orchestrators\." "from tools\." "from ui\."; do
  grep -r "$pattern" --include="*.py" src/ tests/ scripts/ && echo "⚠ Found old import: $pattern" || true
done
```
```

### Step 4.5: Manually verify critical files

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
from transactoid.infra.db.models import Base
```

**Scripts that use Taxonomy + DB together**:
```python
# Before
from services.db import DB
from services.taxonomy import Taxonomy

db = DB(url)
taxonomy = Taxonomy.from_db(db)

# After
from transactoid.infra.db.facade import DB
from transactoid.taxonomy.loader import load_taxonomy_from_db

db = DB(url)
taxonomy = load_taxonomy_from_db(db)
```

**Tools that call save_transactions**:
```python
# Before
outcome = db.save_transactions(taxonomy, txns)

# After
from transactoid.taxonomy.loader import get_category_id
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
python -c "from transactoid.taxonomy.core import Taxonomy; print('✓ Taxonomy imports')"
python -c "from transactoid.infra.db.facade import DB; print('✓ DB imports')"
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

# Test UI
uv run pytest tests/ui/ -v
# Expected: All pass
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

**ONLY AFTER** all imports are updated and tests pass.

```bash
# Verify all moved to src/ before deleting
find src/transactoid -type f -name "*.py" | wc -l
# Should be >100 files

# Verify no import errors with new structure
python -c "
from transactoid.infra.db.facade import DB
from transactoid.taxonomy.core import Taxonomy
from transactoid.ui.cli import app
from transactoid.orchestrators.transactoid import Transactoid
print('✓ All critical imports work')
"

# Remove old root directories (after verifying copies exist)
rm -rf services/
rm -rf ui/  # OLD ui, not the one in src/transactoid/ui/
rm -rf adapters/
rm -rf frontends/
rm -rf tools/  # ONLY IF all files moved to src/transactoid/tools/
rm -rf orchestrators/  # ONLY IF all files moved
rm -rf prompts/ 2>/dev/null
rm -rf core/ 2>/dev/null

# Keep:
rm -rf models/ 2>/dev/null  # KEEP: models/ at root level!
```

**Verification before deleting**:
```bash
# Should have moved, not copied
diff -r tools/ src/transactoid/tools/ 2>/dev/null && echo "⚠ Files still in both locations" || true
diff -r orchestrators/ src/transactoid/orchestrators/ 2>/dev/null && echo "⚠ Files still in both locations" || true
```

---

## Phase 9: Comprehensive Verification & Testing

### Step 9.1: Import resolution check (CRITICAL - DO THIS FIRST)

```bash
# BEFORE running pytest, verify imports resolve
python -c "
import sys
modules = [
    'transactoid.infra.db.facade',
    'transactoid.infra.db.models',
    'transactoid.taxonomy.core',
    'transactoid.taxonomy.loader',
    'transactoid.infra.clients.plaid',
    'transactoid.infra.cache.file_cache',
    'transactoid.utils.yaml',
    'transactoid.orchestrators.transactoid',
    'transactoid.ui.cli',
]

for mod in modules:
    try:
        __import__(mod)
        print(f'✓ {mod}')
    except ImportError as e:
        print(f'✗ {mod}: {e}')
        sys.exit(1)

print('\\nAll import paths resolve correctly!')
"

# If any fail, fix pyproject.toml or import issues before proceeding
```

### Step 9.2: Check for circular imports

```bash
# Verify no cycles
python << 'EOF'
import sys
import importlib

modules_to_check = [
    'transactoid.taxonomy.core',
    'transactoid.taxonomy.loader',
    'transactoid.infra.db.facade',
    'transactoid.infra.db.models',
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

### Step 9.3: Syntax and static checks

```bash
# Type checking
uv run mypy --config-file mypy.ini src/ tests/ || echo "⚠ Fix type errors before proceeding"

# Linting
uv run ruff check src/ tests/ scripts/ || echo "⚠ Fix linting errors"

# Formatting
uv run ruff format --check src/ tests/ scripts/ || echo "⚠ Code needs formatting"

# Dead code
uv run deadcode src/ || echo "⚠ Check for dead code"
```

### Step 9.4: Runtime checks

```bash
# Test entry point
transactoid --help
# Expected: Shows CLI help without ImportError

# Run all tests
uv run pytest tests/ -v

# If tests fail, check:
# 1. Are there old imports (from services, from tools, etc.) still present?
# 2. Did all files get copied to src/?
# 3. Is pyproject.toml configured correctly?
```

### Step 9.5: Verify Alembic works

```bash
# Alembic should be able to import the models
python -c "from transactoid.infra.db.models import Base; print('✓ Alembic imports OK')"

# Try running a simple alembic command
python -m alembic --version  # Should work
python -m alembic current    # Should show current revision
```

### Step 9.6: Check for old imports lingering

```bash
# Should have ZERO old imports in source code
grep -r "from services\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old services imports found!" && exit 1 || echo "✓ No old services imports"
grep -r "from adapters\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old adapters imports found!" && exit 1 || echo "✓ No old adapters imports"
grep -r "from frontends\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old frontends imports found!" && exit 1 || echo "✓ No old frontends imports"

# Can have these in old root directories (before deletion), but not in src/ or tests/
grep -r "from orchestrators\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old orchestrators imports in source!" && exit 1 || true
grep -r "from tools\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old tools imports in source!" && exit 1 || true
grep -r "from ui\." --include="*.py" src/ tests/ scripts/ && echo "ERROR: Old ui imports in source!" && exit 1 || true

echo "✓ All imports updated to new paths"
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
| 1 | Create directory structure | 15 min |
| 1.5 | Update pyproject.toml + verify | 20 min |
| 2 | Migrate services/ (with split & refactor) | 90 min |
| 3 | Move core packages + UI consolidation | 40 min |
| 4 | Update imports (sequential blocks) | 120 min |
| 5 | Remove dead code | 10 min |
| 6 | Consolidate UI (final) | 15 min |
| 7 | Delete old root directories | 10 min |
| 8 | ~~Verification & testing~~ | ~~60 min~~ |
| 9 | Comprehensive verification | 90 min |
| 10 | Reorganize tests | 30 min |
| 11 | Final cleanup & commit | 20 min |
| **Total** | | **5-7 hours** |

**Key changes from original estimate**:
- **+3 hours** for realistic import update work (sequential blocks, manual fixes)
- **-15 min** from Phase 4 (structured approach is faster than single script)
- **+30 min** Phase 9 (comprehensive verification with entry point, Alembic checks)

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
