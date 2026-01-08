<div align="center">

# Transactoid

**The AI Personal Finance Agent**

[Documentation](#documentation) | [Quick Start](#quick-start) | [Contributing](#contributing)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

</div>

## What is Transactoid?

Transactoid is a CLI-first personal finance agent that ingests your transactions (via Plaid or CSV), intelligently categorizes them using LLMs, and answers natural language questions about your spending. Unlike traditional finance apps, Transactoid puts you in control with a transparent, scriptable workflow and no hidden data handoffs.

**Key capabilities:**
- **Bank Connection**: Connect real bank accounts via Plaid (sandbox or production)
- **Smart Categorization**: LLM-powered transaction categorization with a compact two-level taxonomy (e.g., `FOOD.GROCERIES`, `TRAVEL.FLIGHTS`)
- **Natural Language Queries**: Ask questions like "How much did I spend on dining last month?" and get SQL-backed answers
- **Deterministic Persistence**: Deduplicated storage with immutable verified rows
- **CLI-First**: Full control via command line — no black box, fully scriptable

## Quick Start

```bash
# Clone the repo
git clone https://github.com/adambossy/transactoid.git
cd transactoid

# Install dependencies
pip install uv
uv sync

# Set up environment (see detailed setup below)
cp .env.example .env
# Edit .env with your API keys

# Run the agent
transactoid
```

## Prerequisites

- **Python 3.12+**
- **PostgreSQL** (or SQLite for development)
- **OpenAI API key** (for LLM-based categorization)
- **Plaid account** (for bank connections — free development tier available)

## Detailed Setup

### 1. Install Dependencies

```bash
# Install uv (modern Python package manager)
pip install uv

# Install project dependencies
uv sync

# Install dev dependencies (for running tests and linting)
uv sync --group dev
```

### 2. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# OpenAI (required for categorization)
OPENAI_API_KEY=sk-...

# Database (defaults to SQLite if not set)
DATABASE_URL=postgresql://user:password@localhost:5432/transactoid

# Plaid credentials (see Plaid Setup section)
PLAID_CLIENT_ID=your_client_id
PLAID_ENV=development  # or: sandbox, production
PLAID_SANDBOX_SECRET=your_sandbox_secret
PLAID_DEVELOPMENT_SECRET=your_development_secret
# PLAID_PRODUCTION_SECRET=your_production_secret  # if using production
```

### 3. Plaid Setup

Transactoid uses [Plaid](https://plaid.com) to securely connect to your bank accounts. You'll need to set up a Plaid account to use the bank connection features.

#### Creating a Plaid Account

1. **Sign up** at [dashboard.plaid.com](https://dashboard.plaid.com/signup)
2. **Get your credentials**:
   - Navigate to **Team Settings > Keys**
   - Copy your `client_id`
   - Copy your secrets (Sandbox, Development, and/or Production)

#### Choosing a Plaid Environment

| Environment | Use Case | Data | Cost |
|-------------|----------|------|------|
| **Sandbox** | Testing with fake data | Simulated transactions | Free |
| **Development** | Testing with real banks | Real transactions (100 items free) | Free tier |
| **Production** | Full deployment | Real transactions | Paid |

For personal use with real bank data, **Development** mode is recommended — it provides access to real financial institutions with a generous free tier.

#### Registering the Redirect URI

Plaid requires OAuth redirect URIs to be registered in your dashboard:

1. Go to **Team Settings > API** in your Plaid dashboard
2. Under **Allowed redirect URIs**, add:
   ```
   https://localhost:8443/plaid-link-complete
   ```
3. Save changes

### 4. SSL Certificate Setup (Required for Plaid OAuth)

Plaid's OAuth flow requires HTTPS. Generate a self-signed certificate for local development:

```bash
# Create the .certs directory
mkdir -p .certs

# Generate a private key and self-signed certificate
openssl req -x509 -newkey rsa:4096 \
  -keyout .certs/plaid_redirect_localhost.key \
  -out .certs/plaid_redirect_localhost.crt \
  -days 365 -nodes \
  -subj "/CN=localhost"

# Verify the files were created
ls -la .certs/
```

> **Note**: The certificate (`.crt`) is safe to commit; the private key (`.key`) is gitignored and should never be shared.

### 5. Database Setup

For development, SQLite works out of the box. For production use:

```bash
# Create PostgreSQL database
createdb transactoid

# Set DATABASE_URL in .env
DATABASE_URL=postgresql://localhost/transactoid
```

### 6. Running Transactoid

#### Start the Plaid Redirect Server

Before connecting bank accounts, start the OAuth redirect server in a separate terminal:

```bash
transactoid plaid-serve
```

This starts an HTTPS server on `https://localhost:8443` that handles Plaid OAuth callbacks.

> **Browser Warning**: Your browser will show a security warning for the self-signed certificate. Click "Advanced" and proceed to localhost.

#### Run the Agent

```bash
# Start the interactive agent
transactoid

# Or explicitly:
transactoid agent
```

The agent will prompt you to connect accounts and answer questions about your finances.

## CLI Commands

```bash
# Main entry point — starts the interactive agent
transactoid

# Run pipelines
transactoid run sync --access-token <token>    # Sync transactions from Plaid
transactoid run pipeline --access-token <token>  # Full sync → categorize → persist

# Plaid utilities
transactoid plaid-serve                         # Start OAuth redirect server
transactoid plaid-dedupe-items [--apply]        # Find/remove duplicate Plaid items

# Agent interfaces
transactoid agent                               # Interactive CLI agent
transactoid acp                                 # Agent Client Protocol server

# Evaluation
transactoid eval --input evals/config/questions.yaml
```

## Architecture

Transactoid follows a three-layer architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI / UI Layer                         │
│  transactoid agent | transactoid acp | transactoid plaid-*  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrators Layer                       │
│         Transactoid agent loop (OpenAI Agents SDK)          │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                       Tools Layer                            │
│   SyncTool | CategorizeTool | PersistTool | QueryTool       │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     Adapters Layer                           │
│    PlaidClient | DB Facade | FileCache | Taxonomy           │
└─────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
transactoid/
├── src/transactoid/
│   ├── orchestrators/    # Agent loops and orchestration
│   ├── tools/            # Sync, categorize, persist, query
│   ├── adapters/         # Plaid client, DB, cache
│   ├── taxonomy/         # Two-level category system
│   └── ui/               # CLI, ACP server, chatkit
├── configs/              # Taxonomy definitions
├── scripts/              # Standalone utilities
├── tests/                # Unit and integration tests
└── evals/                # Agent evaluation harness
```

## Taxonomy

Transactoid uses a two-level category taxonomy for transaction categorization:

| Parent Category | Example Children |
|----------------|------------------|
| `income` | `salary_and_wages`, `bonus_and_commission`, `interest_and_dividends` |
| `food_and_dining` | `groceries`, `restaurants`, `coffee_shops`, `delivery_and_takeout` |
| `housing_and_utilities` | `rent`, `mortgage_payment`, `electricity`, `internet` |
| `transportation_and_auto` | `fuel`, `public_transit`, `rides_and_taxis`, `parking_and_tolls` |
| `travel` | `flights`, `lodging`, `hotels`, `activities_and_tours` |
| `shopping_and_personal_care` | `clothing_and_accessories`, `electronics_and_gadgets` |
| ... | See `configs/taxonomy.yaml` for full list |

Categories are validated via `taxonomy.is_valid_key(key)` to ensure consistency.

## Development

### Running Tests

```bash
# Run all tests
uv run pytest -q

# Run specific test
uv run pytest tests/path/to/test.py::test_function -v

# Run with coverage
uv run pytest --cov=transactoid
```

### Linting and Formatting

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run mypy --config-file mypy.ini .

# Dead code detection
uv run deadcode .
```

### Pre-commit Checks

Before committing, ensure all checks pass:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy --config-file mypy.ini . && uv run deadcode .
```

## Troubleshooting

### Plaid OAuth Issues

**"Redirect server not running"**
- Ensure `transactoid plaid-serve` is running in a separate terminal

**"Certificate error in browser"**
- This is expected with self-signed certs
- Click "Advanced" → "Proceed to localhost" (varies by browser)

**"Invalid redirect URI"**
- Verify `https://localhost:8443/plaid-link-complete` is registered in your Plaid dashboard

### Database Issues

**"Cannot connect to database"**
- Check `DATABASE_URL` in your `.env` file
- For SQLite, ensure the directory is writable
- For PostgreSQL, ensure the service is running

### LLM Categorization Issues

**"OpenAI API error"**
- Verify `OPENAI_API_KEY` is set correctly
- Check your OpenAI account has available credits

## Documentation

| Document | Description |
|----------|-------------|
| [CLAUDE.md](CLAUDE.md) | Claude Code development guidelines |
| [AGENTS.md](AGENTS.md) | Unit test structure rules |
| [docs/ruff-guide.md](docs/ruff-guide.md) | Linting and formatting rules |
| [docs/mypy-guide.md](docs/mypy-guide.md) | Type checking configuration |

## Contributing

Contributions are welcome! Before submitting a PR:

1. Ensure all lint checks pass (`ruff check .`)
2. Ensure formatting is correct (`ruff format .`)
3. Ensure type checks pass (`mypy --config-file mypy.ini .`)
4. Ensure tests pass (`pytest -q`)
5. Keep commits focused with clear messages

## License

This project is currently unlicensed. Please contact the maintainers for usage terms.
