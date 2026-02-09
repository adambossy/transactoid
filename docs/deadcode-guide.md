# Deadcode Configuration Guide

> This document must stay in lock-step with `[tool.deadcode]` in `pyproject.toml`. When you edit the configuration, update this guide so that future editors (humans or LLMs) understand why each directive exists and how to exercise it.

## exclude

Skips entire paths that only contain generated or third-party code so they do not pollute the report.

Current project excludes include `.venv/`, `.worktrees/`, migration directories,
and framework-wired modules (`db/migrations/**`, `evals/core/**`,
`src/transactoid/jobs/report/**`, `src/transactoid/ui/mcp/server.py`,
`src/transactoid/ui/cli.py`, `src/transactoid/ui/chatkit/server.py`,
`src/transactoid/ui/chatkit/adapter.py`, `scripts/run.py`,
`src/transactoid/adapters/db/models.py`) so deadcode focuses on normal code
paths.

**Without (`docs/` not excluded)**

```shell
$ deadcode docs/api_reference.py
docs/api_reference.py:1:0: DC01 Variable `EXAMPLE_CONSTANT` is never used
```

```python
# docs/api_reference.py
EXAMPLE_CONSTANT = 42
```

**With (`docs/` listed in exclude)**

```toml
[tool.deadcode]
exclude = ["docs/"]
```

```shell
$ deadcode docs/api_reference.py
Well done! ✨ 🚀 ✨
```

## ignore-names

Suppresses common sentinel names—like module-level loggers, metadata fields, or wildcard fixtures—that appear unused from static analysis but are required for runtime wiring.

**Without `ignore-names`**

```shell
$ deadcode src/logging.py
src/logging.py:3:0: DC01 Variable `LOGGER` is never used
```

```python
# src/logging.py
import logging

LOGGER = logging.getLogger(__name__)
```

**With `ignore-names = ["logger", "LOGGER", "*_fixture", "created_at", "updated_at", "input_schema", "confidence_level", "detailed", "primary", "enum", "properties", "required", ...]`**

```shell
$ deadcode src/logging.py
Well done! ✨ 🚀 ✨
```

## ignore-names-in-files

Tells deadcode to skip unused-name reports inside matching files. We use it to keep fixtures and re-export modules quiet.

**Without `tests/**` in `ignore-names-in-files`**

```shell
$ deadcode tests/test_feature.py
tests/test_feature.py:4:0: DC02 Function `user_fixture` is never used
```

```python
# tests/test_feature.py
import pytest

@pytest.fixture
def user_fixture():
    return {"name": "Ada"}
```

**With `ignore-names-in-files = ["tests/**", "test/**", "*/__init__.py"]`**

```shell
$ deadcode tests/test_feature.py
Well done! ✨ 🚀 ✨
```

## ignore-definitions

Temporarily disables analysis for definitions whose names match the supplied patterns—handy for generated migration shims that always look unused.

**Without `ignore-definitions`**

```shell
$ deadcode app/users/migrations/0001_initial.py
app/users/migrations/0001_initial.py:1:0: DC03 Class `Migration` is never used
app/users/migrations/0001_initial.py:2:4: DC04 Method `forwards` is never used
```

```python
# app/users/migrations/0001_initial.py
class Migration:
    def forwards(self) -> None:
        ...
```

**With `ignore-definitions = ["Migration", "*Migration", "RecategorizeTool", "TagTransactionsTool", "create_context"]`**

```shell
$ deadcode app/users/migrations/0001_initial.py
Well done! ✨ 🚀 ✨
```

## ignore-definitions-if-inherits-from

Skips entire class bodies when they inherit from known framework base types (e.g., `BaseModel`, `Schema`, `Settings`). This prevents deadcode from flagging declarative data models and protocol/adapter classes that are activated by reflection or framework callbacks.

**Without `ignore-definitions-if-inherits-from`**

```shell
$ deadcode app/models/user.py
app/models/user.py:4:0: DC03 Class `User` is never used
app/models/user.py:5:4: DC04 Method `name` is never used
```

```python
# app/models/user.py
class BaseModel:
    ...

class User(BaseModel):
    def name(self) -> str:
        return "Ada"
```

**With `ignore-definitions-if-inherits-from = ["BaseModel", "Schema", "Settings", "Protocol", "BaseHTTPRequestHandler", "_StoreBase"]`**

```shell
$ deadcode app/models/user.py
Well done! ✨ 🚀 ✨
```

## ignore-definitions-if-decorated-with

Skips definitions registered via decorators where runtime dispatch, not direct
Python references, drives usage (for example MCP tools and Typer commands).

Current project includes:
- `mcp.tool`
- `mcp.prompt`
- `app.command`
- `run_app.command`
- `app.callback`
- `app.get`
- `app.post`
- `function_tool`
