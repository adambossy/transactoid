## Transactoid — personal finance agent (CLI-first)

Transactoid ingests your transactions (CSV or Plaid), normalizes them, categorizes each with a taxonomy-aware LLM (single pass with optional self-revision), persists them with dedupe and verified-row immutability, and answers natural-language questions by generating SQL queries. The workflow is intentionally CLI/script-driven—no hidden handoffs.


### Why this exists
- **LLM-assisted categorization**: High-quality categories via a compact two-level taxonomy and explicit prompt keys.
- **Deterministic persistence**: Verified rows are immutable; duplicates are de-duplicated by `(external_id, source)`.
- **Developer ergonomics**: Local JSON file cache for LLM calls; clean interfaces for agents, tools, and services.


## Status
Early groundwork is in place. The concrete requirements and interfaces are defined in the plans; implementation will be layered in this order:
1) `services/file_cache.py`
2) `services/plaid_client.py`
3) `services/db.py` (ORM + façade)
4) `services/taxonomy.py`
5) `tools/sync/sync_tool.py` → calls Plaid sync API and categorizes transactions
6) `tools/categorize/categorizer_tool.py` → `CategorizedTransaction`
7) `tools/persist/persist_tool.py`
8) CLI and scripts

See: `plans/transactoid-requirements.md` and `plans/transactoid-interfaces.md`.


## Features (from the spec)
- **Sync**: Calls Plaid's transaction sync API and categorizes all results using an LLM.
- **Categorization**: Single concrete `Categorizer` (batch-only), prompt key `categorize-transactions`.
- **Taxonomy**: Two-level keys (e.g., `FOOD.GROCERIES`), validation via `taxonomy.is_valid_key(key)`.
- **Persistence**: Upsert `(external_id, source)`; immutable `is_verified` rows; deterministic merchant normalization; tag and bulk recategorization helpers.
- **Analytics**: Natural language questions answered by generating SQL queries for `DB.run_sql`.
- **Database façade**: `DB.run_sql(sql, model, pk_column)` executes SQL queries.
- **File cache**: Namespaced JSON cache with atomic writes and deterministic keys.
- **CLI**: `transactoid` with commands for `sync`, `ask`, `recat`, `tag`, `init-db`, `seed-taxonomy`, `clear-cache`.

Details and exact types live in the `plans/` docs.


## Quickstart
### Requirements
- Python 3.12+
- macOS/Linux recommended

### Setup (development)
```bash
# Clone and enter the repo
git clone <your-fork-or-clone-url> && cd transactoid

# (Optional) Create a virtual environment
python3.12 -m venv .venv && source .venv/bin/activate

# Install dev tooling (ruff, mypy, deadcode) if not already available
python -m pip install -U pip
python -m pip install ruff mypy deadcode

# Run tests
pytest -q
```

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file mypy.ini .
uv run deadcode .
```


## CLI (planned)
`transactoid` (Typer) will expose:
- `sync --access-token <token> [--cursor <cursor>] [--count N]` — sync and categorize Plaid transactions
- `ask "<question>"`
- `recat --merchant-id <id> --to <CATEGORY_KEY>`
- `tag --rows <ids> --tags "<names>"`
- `init-db`
- `seed-taxonomy [yaml]`
- `clear-cache [namespace]`

Until the CLI lands, use the underlying scripts as they are introduced in `scripts/`.


## Running the Agent

Transactoid exposes its agent through three different interfaces, each suited for different use cases. Before running the agent, ensure your environment is configured (see [Quickstart](#quickstart)).

### Option 1: ACP (Agent Client Protocol) — Recommended

ACP is an open protocol that allows any compatible client to communicate with AI agents. We recommend [Toad](https://github.com/batrachianai/toad), a polished terminal UI for AI agents.

#### Install Toad

```bash
# Quick install
curl -fsSL batrachian.ai/install | sh

# Or via UV
uv tool install -U batrachian-toad --python 3.14
```

#### Run with Toad

```bash
# Start the Plaid redirect server (in a separate terminal)
transactoid plaid-serve

# Launch Toad with Transactoid
toad acp "uv run transactoid acp 2>/tmp/transactoid.log" -t "Transactoid"
```

This launches Toad's terminal UI with Transactoid as the backend agent. Logs are written to `/tmp/transactoid.log` (ACP uses stdout for JSON-RPC communication).

> **Note**: Toad works with any ACP-compatible agent. See [agentclientprotocol.com](https://agentclientprotocol.com) for the protocol spec.

### Option 2: MCP (Model Context Protocol) — For AI Assistants

MCP exposes Transactoid's tools to AI assistants like Claude Code, allowing them to query your transactions, sync accounts, and run SQL on your behalf.

#### Configure Claude Code

Add Transactoid as an MCP server in your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "transactoid": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/transactoid", "python", "-m", "transactoid.ui.mcp.server"],
      "env": {
        "DATABASE_URL": "sqlite:///path/to/your/transactoid.db",
        "PLAID_CLIENT_ID": "your_client_id",
        "PLAID_ENV": "development",
        "PLAID_DEVELOPMENT_SECRET": "your_secret"
      }
    }
  }
}
```

#### Set a Custom System Prompt (Optional)

To give Claude Code context about your financial data, add a custom system prompt. Create or edit `~/.claude/CLAUDE.md`:

```markdown
# Transactoid Finance Agent

You have access to Transactoid MCP tools for personal finance analysis:

- `sync_transactions`: Fetch latest transactions from connected Plaid accounts
- `connect_new_account`: Link a new bank account via Plaid
- `list_plaid_accounts`: Show all connected accounts
- `run_sql`: Query the transaction database
- `recategorize_merchant`: Bulk update categories for a merchant
- `tag_transactions`: Apply tags to transactions

When answering finance questions, use `run_sql` to query the `derived_transactions`
table (not `plaid_transactions`). Always filter by category to distinguish spending
from income/transfers.
```

#### Available MCP Tools

| Tool | Description |
|------|-------------|
| `sync_transactions` | Fetch and categorize latest transactions from Plaid |
| `connect_new_account` | Initiate Plaid Link to connect a new bank |
| `list_plaid_accounts` | List all connected Plaid items |
| `run_sql` | Execute read-only SQL queries |
| `recategorize_merchant` | Bulk update category for a merchant |
| `tag_transactions` | Apply tags to matching transactions |

> **Note**: MCP works with any MCP-compatible client, not just Claude Code. See [modelcontextprotocol.io](https://modelcontextprotocol.io) for other integrations.

### Option 3: ChatKit — Web UI Integration

ChatKit provides an HTTP server compatible with OpenAI's ChatKit SDK, allowing integration with web-based chat interfaces.

#### Start the Server

```bash
# Start the Plaid redirect server (in a separate terminal)
transactoid plaid-serve

# Start the ChatKit server
uv run python -m transactoid.ui.chatkit.server
```

The server runs at `http://localhost:8000/chatkit` and accepts ChatKit-formatted requests.

#### Integration

ChatKit is designed for building custom web frontends. It exposes a `/chatkit` endpoint that handles:
- Conversation threading
- Streaming responses
- Tool call execution

See the [OpenAI ChatKit SDK documentation](https://github.com/openai/chatkit) for client integration details.

### Quick Reference

| Interface | Best For | Command |
|-----------|----------|---------|
| **ACP + Toad** | Interactive terminal use | `toad acp "uv run transactoid acp 2>/tmp/transactoid.log" -t "Transactoid"` |
| **MCP + Claude Code** | AI-assisted finance queries | Configure in `~/.claude/settings.json` |
| **ChatKit** | Web UI integration | `uv run python -m transactoid.ui.chatkit.server` |


## Architecture overview
- **Agents**
  - `transactoid`: core agent loop
- **Tools**
  - `tools/sync/sync_tool.py`: Calls Plaid sync API and categorizes transactions using LLM.
  - `tools/categorize/categorizer_tool.py`: `Categorizer` produces `CategorizedTransaction`.
  - `tools/persist/persist_tool.py`: upsert + immutability + tags + bulk recats.
- **Services**
  - `services/db.py`: ORM models + façade (`run_sql`, lookups, helpers).
  - `services/taxonomy.py`: in-memory two-level taxonomy and prompt helpers.
  - `services/plaid_client.py`: minimal Plaid wrapper.
  - `services/file_cache.py`: namespaced JSON file cache with atomic writes.

For full signatures and dependencies, see `plans/transactoid-interfaces.md`.


## Local development
### Repo layout (high level)
```
transactoid/
  agents/         # Orchestration for categorization & analytics
  tools/          # Sync, categorize, persist helpers
  services/       # DB, taxonomy, plaid client, file cache
  ui/             # CLI entrypoint
  scripts/        # Runnable orchestrators
  prompts/        # Prompt sources for Promptorium
  db/             # Schema and migrations
  tests/          # Unit tests
```

### Coding standards
- Python 3.12 typing; prefer explicit types on public APIs.
- Keep functions small, use guard clauses, and avoid deep nesting.
- Only add comments where they carry non-obvious rationale.


## Tooling
The project ships docs for our tools and their rationale:
- `docs/ruff-guide.md` — Linting and formatting rules.
- `docs/mypy-guide.md` — Type-checking modes and overrides.
- `docs/pre-commit-guide.md` — Suggested hooks and usage.
- `docs/deadcode-guide.md` — How we detect unused code.

Common commands (local installs or via `uv run`):
```bash
# Lint
ruff check .

# Format (or check formatting)
ruff format .          # or: ruff format --check .

# Type-check
mypy --config-file mypy.ini .

# Dead code
deadcode .
```


## File cache (available now)
`services/file_cache.py` provides a namespaced JSON cache with atomic writes and deterministic keys. Example:
```python
from services.file_cache import FileCache, stable_key

cache = FileCache(base_dir=".cache")
payload = {"a": 1, "b": 2}
key = stable_key(payload)

cache.set("llm", key, {"result": "ok"})
assert cache.get("llm", key) == {"result": "ok"}
```

Default cache directory is `.cache/`. Keys and namespaces are validated to prevent path traversal.

For the authoritative spec, consult:
- `plans/transactoid-requirements.md`
- `plans/transactoid-interfaces.md`
- `plans/file-cache.md`


## Contributing
Issues and PRs are welcome. Keep commits focused and ensure:
- Ruff passes (including format).
- Mypy passes (`mypy.ini` settings).
- Dead code checks are clean.
- Tests pass and are easy to read (concise test names, clear input/output).
