# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Transactoid is a personal finance agent that ingests transactions (CSV or Plaid), categorizes them using LLM-based categorization with a two-level taxonomy, and answers natural-language questions about your personal finances. The project is CLI-first with no hidden handoffs.

**Core Principles:**
- LLM-assisted categorization with compact two-level taxonomy
- Deterministic persistence with immutable verified rows
- Local JSON file cache for LLM calls

## Development Commands

### Testing and Linting
```bash
# Run tests
uv run pytest -q

# Run single test
uv run pytest tests/path/to/test.py::test_function_name -v

# Lint
uv run ruff check .

# Format (check)
uv run ruff format --check .

# Format (apply)
uv run ruff format .

# Type-check
uv run mypy --config-file mypy.ini .

# Dead code detection
uv run deadcode .
```

### Running the CLI
```bash
# The main entrypoint (currently calls transactoid agent)
transactoid

# Planned CLI commands (not yet implemented):
# transactoid sync --access-token <token> [--cursor <cursor>] [--count N]
# transactoid ask "<question>"
# transactoid recat --merchant-id <id> --to <CATEGORY_KEY>
# transactoid tag --rows <ids> --tags "<names>"
# transactoid init-db
# transactoid seed-taxonomy [yaml]
# transactoid clear-cache [namespace]
```

## Architecture

### Three-Layer Structure

**Agents** (`agents/`): Orchestration loops that coordinate tools
- `transactoid.py`: Main agent for sync → categorize → persist workflow

**Tools** (`tools/`): Self-contained units that perform specific operations
- `tools/ingest/`: CSV and Plaid transaction ingestion with bank-specific adapters
  - `csv.py`: CSV ingestion using bank adapters
  - `plaid.py`: Plaid API ingestion
  - `adapters/`: Bank-specific CSV parsers (Amex, Chase, Alliant, etc.)
- `tools/categorize/`: LLM-based transaction categorization
  - `categorizer_tool.py`: Produces `CategorizedTransaction` using taxonomy
- `tools/persist/`: Database persistence with upsert, immutability, tagging
  - `persist_tool.py`: Handles dedupe by `(external_id, source)`
- `tools/sync/`: Combined Plaid sync + categorization
  - `sync_tool.py`: Orchestrates Plaid fetch and LLM categorization

**Services** (`services/`): Shared infrastructure
- `file_cache.py`: Namespaced JSON cache with atomic writes, deterministic keys
- `taxonomy.py`: Two-level category taxonomy (e.g., `FOOD.GROCERIES`)
- `db.py`: ORM models + façade with `run_sql()` for query execution
- `plaid_client.py`: Minimal Plaid API wrapper

### Key Concepts

**Ingest Flow:**
1. `IngestTool` implementations (`CSVIngest`, `PlaidIngest`) fetch transactions
2. Bank-specific adapters normalize CSV formats to `NormalizedTransaction`
3. Tools yield batches via `fetch_next_batch(batch_size)`

**Categorization:**
- Single `Categorizer` uses two-level taxonomy keys
- Prompt key: `categorize-transactions`
- Results cached via `FileCache` with deterministic keys

**Persistence:**
- Dedupe by `(external_id, source)` tuple
- Immutable rows when `is_verified=True`
- Merchant normalization is deterministic
- Support for tags and bulk recategorization

**Analytics:**
- DB façade runs SQL via `DB.run_sql(sql, model, pk_column)`
- Natural language questions are answered by the agent constructing SQL with which to call `DB.run_sql`

## File Cache

The `FileCache` service provides deterministic JSON caching for LLM calls:

```python
from services.file_cache import FileCache, stable_key

cache = FileCache(base_dir=".cache")
payload = {"prompt": "...", "model": "..."}
key = stable_key(payload)

# Check cache before LLM call
cached = cache.get("llm", key)
if cached:
    return cached["result"]

# Cache miss: call LLM and store
result = llm_call(payload)
cache.set("llm", key, {"result": result})
```

Default cache directory: `.cache/`
Namespaces validate against path traversal.

## Taxonomy Structure

Two-level keys: `PARENT.CHILD`
- Example: `FOOD.GROCERIES`, `HOUSING.RENT`
- Validation: `taxonomy.is_valid_key(key)`
- Seed file: `configs/taxonomy.yaml`

## Type Checking Configuration

mypy is configured in **strict mode** with additional constraints:
- `disallow_any_expr = True`
- `disallow_any_return = True`
- `disallow_any_decorated = True`
- `disallow_any_unimported = True`

All public APIs require explicit type annotations. Tests have relaxed rules.

## Unit Test Structure

Follow the Input → Setup → Act → Expected → Assert pattern from AGENTS.md:

1. **Input first**: Define `input = {...}` as simple literals
2. **Setup via helpers**: Use `create_*` functions for complex setup
3. **Act**: Single call to function under test
4. **Expected**: Build `expected_output = {...}` explicitly
5. **Assert**: Single `assert output == expected_output`

**Helpers:**
- `_as_dict(obj)`: Convert objects to dicts for equality checks
- `create_*`: Factory functions returning test instances
- `_fetch_one_as_dict(unit, batch_size)`: Wrapper that asserts length internally

**Naming:**
- Tests: `test_<unit>_<behavior>[_<condition>]` (no "should")
- Helpers: verbs like `build_csv_dir_with`, `create_*`

**Data:**
- Use `tmp_path` fixture for file tests
- Prefer deterministic data over random generation
- Use `pytest.importorskip` for optional dependencies

## Linting and Formatting

**Ruff configuration** (`ruff.toml`):
- Line length: 88
- Target: Python 3.12
- Enabled rules: flake8-bugbear, comprehensions, isort, pyupgrade, bandit
- Tests ignore S101 (assert statements)

**Before completing work:**
Always run all four checks: ruff check, ruff format, mypy, deadcode

## Project Status

Early implementation phase. Core infrastructure (file cache, taxonomy) is in place.

**Implementation order** (from README):
1. ✅ `services/file_cache.py`
2. `services/plaid_client.py`
3. `services/db.py` (ORM + façade)
4. `services/taxonomy.py`
5. `tools/sync/sync_tool.py`
6. `tools/categorize/categorizer_tool.py`
7. `tools/persist/persist_tool.py`
8. CLI and scripts

**Reference docs:**
- `plans/transactoid-spec.md`: Requirements and interfaces
- `plans/file-cache.md`: File cache design
- `AGENTS.md`: Unit test structure rules

## Important Notes

- Never commit `.env` files (contains Plaid tokens)
- Verified transactions (`is_verified=True`) are immutable in DB
- Use `uv run` prefix for all dev tools to ensure proper environment
