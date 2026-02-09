Responses must ALWAYS begin with the fox emoji: 🦊

### Linting and verification

Before completing your work, always run the linter, type-checker, code formatter and dead code detector.

Commands:
```bash
# Lint
uv run ruff check .

# Format (or check formatting)
uv run ruff format .          # or: ruff format --check .

# Type-check
uv run mypy --config-file mypy.ini .

# Dead code
uv run deadcode .

# Tests
uv run pytest -q
```

### Planning artifacts

Whenever you create a plan, record it in a `.md` file named with a sortable timestamp (to the second) plus a unique plan name so files sort from earliest to latest.
Examples: `20260207-143522-refactor-dedupe.md`, `20260207-143522-eval-runner-cleanup.md`.

### Unit test structure rules

- Input first
  - Define `input = ...` as simple literals/dicts/dataclasses.
  - Keep inputs minimal but representative; avoid irrelevant fields.

- Setup via helpers
  - If setup >2 lines or uses control flow/IO/mocks, move it into a clearly named helper (e.g., `create_csv_ingest(...)`, `create_plaid_ingest(...)`, `_fetch_one_as_dict(...)`).
  - Helpers should do one thing, return concrete objects/data, and hide incidental asserts (e.g., list length checks).

- Act (function under test)
  - Assign a single `output = <function_under_test>(input)` (or a small wrapper like `_fetch_one_as_dict(...)`).

- Expected
  - Build `expected_output = {...}` explicitly in the test.
  - When comparing rich objects, convert to dicts via `_as_dict(...)` helpers for clean equality checks.

- Assert
  - Prefer one final assertion: `assert output == expected_output`.
  - Use helper-encapsulated checks for incidental validations (length, types) to keep the test body single-assert.
  - For floats use tolerance (e.g., `math.isclose`) inside helpers; for unordered collections compare `set`/`sorted`.

### Naming and readability

- Test names: `test_<unit>_<behavior>[_<condition>]` (no “should”).
- Helpers are verbs (e.g., `build_csv_dir_with`, `create_*`, `_fetch_one_as_dict`).
- Keep tests short and single-responsibility; use `@pytest.mark.parametrize` for small input variations.

### Imports and skipping

- Use direct imports; for optional deps use `pytest.importorskip("package.module", reason="...")` at module top.
- Avoid try/except import skipping in test bodies.

### Data and determinism

- Prefer explicit, deterministic data; encode normalization rules in helpers (e.g., `_normalize_descriptor_for_hash`).
- For file/FS tests, use `tmp_path` and a builder helper to create fixtures cleanly.

### Helper patterns to reuse

- Object-to-dict for equality:
  - `_as_dict(obj)` yielding only fields you care about.
- Builder/factory:
  - `create_*` that returns a constructed instance ready to call.
- Fetch wrappers:
  - `_fetch_one_as_dict(unit, batch_size)` that asserts length internally and returns a dict for equality.

### Minimal template

```python
def test_<unit>_<behavior>():
    # input
    input_data = {...}

    # helper setup
    unit = create_<unit>(input_data)

    # act
    output = function_under_test(unit)

    # expected
    expected_output = {...}

    # assert
    assert output == expected_output
```

# Style Guide

## Purpose

- General coding style guidelines that govern naming, structure, readability, and common patterns. Keep changes minimal and focused; prefer small, intentional diffs.

## Development workflow

- Branch naming
  - Use `<type>/<description>` format with lowercase and hyphens (kebab-case).
  - Types: `feature/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.
  - Example: `feature/add-plaid-sync`, `fix/transaction-dedupe`.

- Worktree merge and cleanup
  - Prefer rebasing the worktree branch onto `main` before merging:
    ```bash
    # In the worktree
    git fetch origin
    git rebase origin/main
    ```
  - Prefer fast-forward merges to avoid merge commits:
    ```bash
    # In the primary repo
    git switch main
    git pull --ff-only
    git merge --ff-only <branch-name>
    ```
  - If fast-forward fails, rebase again and retry `--ff-only` merge instead of creating a merge commit.
  - Remove the worktree directory:
    ```bash
    git worktree remove <worktree-path>
    ```
  - Delete the local branch:
    ```bash
    git branch -d <branch-name>
    ```
  - Delete the remote branch (if it exists):
    ```bash
    git push origin --delete <branch-name>
    ```
  - Prune stale worktree metadata:
    ```bash
    git worktree prune
    ```
  - Optional verification:
    ```bash
    git worktree list
    git branch --list
    ```
- Commit practices
  - Keep commits small and focused. Large commits are harder to review, harder to bisect, and harder to revert.
  - When you have many unstaged changes, analyze the dependency relationships between them. Identify which changes are self-contained and which depend on others.
  - Commit standalone changes first. If file A can be committed independently but file B depends on changes in file A, commit A before B.
  - Each commit must leave the repository in a working state. All tests should pass, and the code should be functional. Changes that depend on each other must be committed together.
  - Group related commits sequentially. If you're making commits A, B, and C where B and C both relate to a feature but A is an unrelated fix, commit in the order A → B → C (not A → B → A-related → C) so the history reads cleanly.
  - When in doubt, err on the side of smaller commits. A series of five small commits is preferable to one large commit containing the same changes.

- General code quality
  - Prefer small functions with descriptive names; split large nested logic into helpers or modules instead of defining nested functions.
  - Keep imports at module top level; avoid importing modules inside functions.
  - Do not use banner comments.

- Database access patterns
  - Avoid N+1 queries. Before writing database code, consider the full data flow and plan batch operations upfront.
  - N+1 on reads: fetching N parent records then issuing N queries for related data. Fix: use JOINs or batch fetch with `IN` clause.
  - N+1 on writes: processing N items then issuing N individual INSERT/UPDATE statements. Fix: use bulk insert/update methods.
  - When designing a function that processes a collection, ask: "Will this hit the database once per item?" If yes, refactor to batch.
  - Prefer `bulk_insert`, `executemany`, or CASE expressions for bulk updates over loops with individual writes.
  - Example anti-pattern:
    ```python
    # BAD: N+1 writes - opens N transactions, ~100ms overhead each
    for item in items:
        db.update_item(item.id, item.value)
    ```
  - Example fix:
    ```python
    # GOOD: Single bulk operation
    updates = {item.id: item.value for item in items}
    db.bulk_update_items(updates)
    ```

## Core style principles

- Readability and predictability
  - Favor straightforward, explicit code over clever tricks.
  - Use a single, well-defined core path for public APIs (one way in, one way out).
  - Choose names that reflect intent (what or who), not implementation.

- Local reasoning and encapsulation
  - Each function/class has one clear responsibility.
  - Encapsulate invariants (validation, canonical forms) so callers can assume them.
  - Minimize coupling, maximize cohesion.

- Graceful extension (open–closed)
  - Provide hooks/adapters so behavior can be extended without changing internals.
  - Layer abstractions cleanly (e.g., transport, serialization, error handling).
  - Define a repository-specific root exception and derive specific subtypes per domain.
  - Do not raise bare `Exception`. Wrap external exceptions so the public surface exposes a consistent error taxonomy.
  - When wrapping external exceptions, chain the original using `raise ... from e` to preserve the cause and traceback:

    ```py
    try:
        do_the_thing()
    except ExternalError as e:
        raise DomainError("Failed to do the thing") from e
    ```

- Maintainability and process hygiene
  - Pair features with tests and documentation.
  - Use the tools configured in `pyproject.toml` (e.g., Ruff for lint/format if present), mypy for type checking, pytest for tests, and pre-commit for hooks.
  - Refactor continuously; eliminate duplication and accidental complexity.
  - Prefer small, purposeful commits with clear messages.

## Readability

- Keep top-level orchestration small; delegate to tiny, focused helpers. A public entrypoint should mostly compose helpers.

- Normalize inputs and precompute early when feasible; preserve original order. When performing rewrite/transformation workflows, keep a stable index (e.g., `pos`) to ensure determinism.

- Group with simple, explicit data structures. Prefer sets, dicts, and lists with clear loops over clever one-liners; introduce specialized structures only when they improve clarity.

- Prefer early returns and small loops over deep nesting. Short-circuit empties and error cases as soon as they are known.

- Inject I/O for testability. Accept `print_fn`, `input_fn`, or a selector callback; avoid capturing patched builtins at import time. Do not bind builtins as default parameter values—default to `None` and assign inside the function body. For example:

  ```py
  def prompt(*, input_fn=None, print_fn=None):
      if input_fn is None:
          input_fn = input
      if print_fn is None:
          print_fn = print
      # use input_fn / print_fn below
  ```

- Validate early with precise errors that include the actual type (e.g., `...; got {type_name}`) for injected callbacks and external inputs.

- Keep user-facing prints short and actionable. Use sentence case, minimal punctuation, and introduce lists with a colon.

- Document non-obvious formatting or ordering choices in a short inline comment near the code that depends on them.

## Naming

- Name by role: nouns for data, verbs for actions. Examples: data `PreparedItem`; actions like `materialize_and_prepare`, `persist_group`, `render_group_context`.

- Use module-private helpers for internals and expose a minimal public API. Prefix internals with a single underscore and (optionally) export the public surface via `__all__`.

- Prefer keyword-only parameters for helpers with multiple arguments or boolean flags. Use `*,` after the primary subject to force clarity at call sites. Avoid boolean flags that change behavior; prefer an `Enum` or strategy object to represent modes.

- Use short, conventional abbreviations only when the context is obvious (e.g., `tx` for transaction, `eid` for external id, `fp` for fingerprint, `pos` for original index, `idx` for index). Otherwise, spell names out.

- Avoid single-letter variable names in new code; choose intention-revealing names instead (e.g., `idx`, `row`, `item`, `count`). Narrow exceptions are allowed in short, self-contained scopes for domain-standard mathematical symbols and widely understood local conventions (e.g., `i`/`j` for algorithmic indices, `x`/`y` for coordinates, `k`/`v` in a one-liner dict comprehension, `n` for sample size). Prefer `idx`/`pos` over `i`/`j` in general-purpose loops.

- Adopt consistent, intention-revealing prefixes:
  - `group_*` for data scoped to the current duplicate group (e.g., `group_items`, `group_eids`).
  - `db_*` for values sourced from the database (e.g., `db_dupes`).
  - `allowed_categories` (a set) for allowed categories; `category_options` (a list) for UI-ready choices; `default_category` for the selected default.

## Boilerplate patterns

- I/O and selector injection
  - Accept injectable `print_fn`, `input_fn`, and a selection function when interaction is needed (defaults noted in Readability). Strip and validate selector returns as strings.

- Validation
  - Guard injected types and external values explicitly; raise with the concrete type name in the message.

- Control flow
  - Prefer early returns for empty inputs, short-circuit unanimous cases, and immediate retries for user-driven flows.

- Data containers
  - Use efficient, intention-revealing containers. Prefer `@dataclass(frozen=True, slots=True)` for immutable prepared records (target Python version is defined in `pyproject.toml`, currently 3.12).

- Comments
  - Reserve comments for intent and non-obvious decisions. Avoid narrating the change itself.

## Logging

- Separate logging logic from business logic
  - Extract logging concerns into a dedicated logger class when logging is non-trivial
  - Keep formatting and presentation logic out of core business methods

- Use structured logging
  - Attach contextual data for queryable logs rather than interpolating into message strings

- Choose appropriate log levels
  - INFO for normal operations and progress
  - DEBUG for detailed diagnostic information
  - WARNING for recoverable issues
  - ERROR for errors that need attention

- Avoid print() in production code
  - Use logger methods instead of print statements
  - Reserve print() only for CLI user interaction or test output

When in doubt, choose the option that improves local readability for the next reader and keeps the public surface simple and predictable.
