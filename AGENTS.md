### Linting and verification

Before completing your work, always run the linter, type-checker, code formatter and dead code deterctor.

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
