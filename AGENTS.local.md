# AGENTS.local.md

@AGENTS.md

Project-specific guidance for working with this repository.

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

## Project Conventions

### CLI Framework
New CLI entry points and any CLI refactors must use Typer. Expose commands via a Typer app; do not hand-roll argparse or custom parsers.

### Environment Loading
Load environment variables from a `.env` file using `python-dotenv`. Call `load_dotenv(override=False)` once in the CLI entrypoint before command execution; do not override variables that are already set.

### Git Worktrees
- Always work in a dedicated worktree located in `.worktrees/<branch-name>` unless already in one. Check the current directory path; if not in `.worktrees/`, create a new worktree and switch to its working directory before starting work.
- Stay inside the worktree for all development work. If you need to switch to main (e.g., to check something), always return to the worktree directory afterward.
- When instructed to clean up a worktree:
  1. Ensure the worktree's branch is pushed to remote
  2. Switch to the main branch worktree
  3. Remove the worktree using `git worktree remove <path>`

### Git Stacking with Graphite
- Track branches in the stack using `gt branch track` after creating a new worktree and checking out the branch
- Before starting work, run `gt sync` to pull remote changes and maintain stack relationships
- Create atomic changesets: treat each branch as a single logical change with one commit. Use `gt modify -a` to amend existing commits rather than adding new commits
- Stage and create new stacked branches with `gt create -am "description"` or `gt c -am "description"` for rapid iteration
- Push stacked changes with `gt submit` or `gt submit --stack` to push all branches in the stack
- Navigate between branches: use `gt up`/`gt down` for adjacent branches or `gt checkout` for interactive selection
- When modifying mid-stack branches, Graphite auto-rebases all dependent branches above
- For concurrent agent work, each agent operates on its own worktree/branch in the stack

### Scale Assumptions
This app targets a single-user workflow. Do not assume external clients, observability stacks, or production-grade frills by default.

### Error Handling
Define the root exception `AppError` in `errors.py` and derive specific subtypes per domain. Raise `AppError` subclasses (not bare `Exception`) so the public surface exposes a consistent error taxonomy.

### Logging
Use loguru for structured logging:
- Import: `import loguru` and `from loguru import logger`
- Type hint: `loguru.Logger` (not `Any`)
- Default instance: Use the pre-configured `logger` object
- Use `.bind()` to attach contextual data for queryable logs
- `logger.success()` is available for positive outcomes

Example pattern for separating logging from business logic:

```python
import loguru
from loguru import logger

class MyComponentLogger:
    """Handles all logging for MyComponent with business logic separated."""

    def __init__(self, logger_instance: loguru.Logger = logger) -> None:
        self._logger = logger_instance

    def operation_start(self, item_count: int, config: str) -> None:
        """Log operation start with context."""
        self._logger.bind(
            item_count=item_count,
            config=config
        ).info("Starting operation with {} items (config: {})", item_count, config)

class MyComponent:
    def __init__(self):
        self._logger = MyComponentLogger()

    def process(self, items: list) -> None:
        self._logger.operation_start(len(items), "default")
        # Business logic here without logging concerns
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
Use 'bd' for task tracking
