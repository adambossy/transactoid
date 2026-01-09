<div align="center">

<img src="assets/transactoid-icon.png" alt="Transactoid" style="vertical-align: middle;" />

<br />

# transactoid

The world's smartest personal finance tool

<p align="center">
  <a href="https://github.com/adambossy/transactoid/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
  &middot;
  <a href="https://github.com/adambossy/transactoid/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  <br />
  <br />
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)
![CLI](https://img.shields.io/badge/CLI-Typer-4E9A06)
![Plaid](https://img.shields.io/badge/Banking-Plaid-00D096)
![OpenAI](https://img.shields.io/badge/LLM-OpenAI-412991)
[![Twitter](https://img.shields.io/badge/Twitter-@abossy-1DA1F2?logo=twitter&logoColor=white)](https://twitter.com/abossy)

</div>

---

Transactoid is an AI agent that analyzes your personal finances with meticulous fidelity and a side of sass. It connects to your bank accounts using Plaid, intelligently categorizes your transactions using the power of LLMs and gives you detailed reports for each and every question you have. Gone are boring, rigid dashboards with piss-poor transaction categorization. Transactoid replaces them with an untethered, occasionally unhinged, curiosity-driven analyst that understands your spending habits better than a bank ever could.

## Running the Agent

Transactoid exposes its agent through three different interfaces, each suited for different use cases.

### Plaid Setup

Transactoid uses [Plaid](https://plaid.com) to connect to your bank accounts. You'll need to create a Plaid account and request **Limited Production** access:

1. Sign up at [dashboard.plaid.com](https://dashboard.plaid.com)
2. Request **Limited Production** access from the Dashboard

Limited Production gives you free access to real bank data for testing purposes. It has some restrictions (capped API calls, limited access to certain large institutions), but it's sufficient for personal use. Full Production access requires additional approval and is usage-based.

Once approved, grab your credentials from the Plaid Dashboard:
- **Client ID** (found in Keys section)
- **Production Secret** (found in Keys section)

### Environment Setup

Create a `.env` file in the project root with the following variables:

```bash
DATABASE_URL=sqlite:///path/to/your/transactoid.db
OPENAI_API_KEY=your_openai_api_key
PLAID_CLIENT_ID=your_plaid_client_id
PLAID_ENV=production
PLAID_PRODUCTION_SECRET=your_plaid_production_secret
```

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
      "args": ["run", "python", "-m", "transactoid.ui.mcp.server"]
    }
  }
}
```

#### Set a Custom System Prompt (Required)

Claude Code requires a system prompt to understand Transactoid's database schema, category taxonomy, and financial analysis patterns. Use the `--system-prompt` flag to replace the default prompt:

```bash
claude --system-prompt "$(cat src/transactoid/prompts/agent-loop/agent-loop-7.md)"
```

This prompt provides Claude with the full context needed to query your transactions, understand categories, and give accurate financial insights.

#### Available MCP Tools

| Tool                    | Description                                         |
| ----------------------- | --------------------------------------------------- |
| `sync_transactions`     | Fetch and categorize latest transactions from Plaid |
| `connect_new_account`   | Initiate Plaid Link to connect a new bank           |
| `list_plaid_accounts`   | List all connected Plaid items                      |
| `run_sql`               | Execute read-only SQL queries                       |
| `recategorize_merchant` | Bulk update category for a merchant                 |
| `tag_transactions`      | Apply tags to matching transactions                 |

> **Note**: MCP works with any MCP-compatible client, not just Claude Code. See [modelcontextprotocol.io](https://modelcontextprotocol.io) for other integrations.

### Option 3: ChatKit — Web UI Integration

ChatKit provides an HTTP server compatible with OpenAI's ChatKit SDK, with a bundled Next.js frontend.

#### Start the Servers

```bash
# Terminal 1: Start the Plaid redirect server
transactoid plaid-serve

# Terminal 2: Start the ChatKit backend server
uv run python -m transactoid.ui.chatkit.server

# Terminal 3: Start the web frontend
cd web && npm install && npm run dev
```

Open http://localhost:3000 in your browser.

#### Architecture

- **Backend**: FastAPI server at port 8000 (`/chatkit` endpoint)
- **Frontend**: Next.js app at port 3000 using `@openai/chatkit-react`

See the [OpenAI ChatKit SDK documentation](https://github.com/openai/chatkit) for customization details.

### Quick Reference

| Interface             | Best For                    | Command                                                                     |
| --------------------- | --------------------------- | --------------------------------------------------------------------------- |
| **ACP + Toad**        | Interactive terminal use    | `toad acp "uv run transactoid acp 2>/tmp/transactoid.log" -t "Transactoid"` |
| **MCP + Claude Code** | AI-assisted finance queries | Configure in `~/.claude/settings.json`                                      |
| **ChatKit**           | Web UI integration          | `uv run python -m transactoid.ui.chatkit.server`                            |

## Architecture overview

- **Tools** (`src/transactoid/tools/`)
  - `sync/`: Calls Plaid sync API and categorizes transactions using LLM.
  - `categorize/`: `Categorizer` produces `CategorizedTransaction`.
  - `persist/`: upsert + immutability + tags + bulk recats.
  - `query/`: SQL query execution.
- **Adapters** (`src/transactoid/adapters/`)
  - `db/`: ORM models + façade (`run_sql`, lookups, helpers).
  - `clients/`: Plaid API wrapper.
  - `cache/`: Namespaced JSON file cache with atomic writes.
- **Taxonomy** (`src/transactoid/taxonomy/`): Two-level category taxonomy and prompt helpers.
- **UI** (`src/transactoid/ui/`): ACP, MCP, and ChatKit servers.

## Local development

### Repo layout (high level)

```
src/transactoid/
  adapters/       # External service adapters (DB, Plaid, cache)
  tools/          # Domain tools (sync, categorize, persist, query)
  taxonomy/       # Category taxonomy and validation
  ui/             # Interface servers (ACP, MCP, ChatKit)
  prompts/        # Prompt sources for Promptorium
tests/            # Unit tests
web/              # Next.js ChatKit frontend
scripts/          # Runnable orchestrators
configs/          # Configuration files (taxonomy.yaml)
docs/             # Tool guides
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

## Contributing

Issues and PRs are welcome. Keep commits focused and ensure:

- Ruff passes (including format).
- Mypy passes (`mypy.ini` settings).
- Dead code checks are clean.
- Tests pass and are easy to read (concise test names, clear input/output).
