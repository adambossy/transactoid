# Mypy Configuration Guide

> This document must stay in lock-step with `mypy.ini`. When you update the configuration, update this guide so that future editors (humans or LLMs) can see why each rule exists and how to exercise it.

## python_version = 3.12

Targets Python 3.12 syntax and standard library typing features. Use this when you rely on 3.12-only typing helpers (e.g., `typing.override`, `TypeVarTuple` refinements).

**Fails (`python_version = 3.11`)**

```ini
# fragment of mypy.ini
[mypy]
python_version = 3.11
```

```shell
$ mypy --config-file mypy.ini sample_python_version.py
sample_python_version.py:2: error: Name "override" is not defined  [name-defined]
```

```python
# sample_python_version.py
from typing import override

class BaseVisitor:
    def visit(self) -> None:
        ...

class ConcreteVisitor(BaseVisitor):
    @override
    def visit(self) -> None:
        print("Visiting")
```

**Passes (`python_version = 3.12`)**

```ini
# fragment of mypy.ini
[mypy]
python_version = 3.12
```

```python
# sample_python_version.py
from typing import override

class BaseVisitor:
    def visit(self) -> None:
        ...

class ConcreteVisitor(BaseVisitor):
    @override
    def visit(self) -> None:
        print("Visiting")
```

## strict = True

Turns on mypy’s bundled strictness flags, including `disallow_any_generics`, `warn_unused_ignores`, and stricter checking of definitions.

**Fails**

```shell
$ mypy --config-file mypy.ini sample_strict.py
sample_strict.py:2: error: Function is missing a type annotation for argument "name"  [no-untyped-def]
sample_strict.py:2: error: Function is missing a return type annotation  [no-untyped-def]
```

```python
# sample_strict.py
def greet(name):
    return "Hello " + name
```

**Passes**

```python
# sample_strict.py
def greet(name: str) -> str:
    return "Hello " + name
```

## show_error_codes = True

Prints error codes alongside diagnostics so you can silence or research them precisely.

**Fails (shows code because `show_error_codes` is on)**

```shell
$ mypy --config-file mypy.ini sample_show_error_codes.py
sample_show_error_codes.py:2: error: Function is missing a type annotation for argument "a"  [no-untyped-def]
sample_show_error_codes.py:2: error: Function is missing a type annotation for argument "b"  [no-untyped-def]
sample_show_error_codes.py:2: error: Function is missing a return type annotation  [no-untyped-def]
```

```python
# sample_show_error_codes.py
def add(a, b):
    return a + b
```

**Passes (fixes the issue so no error code appears)**

```python
# sample_show_error_codes.py
def add(a: int, b: int) -> int:
    return a + b
```

## warn_unused_configs = True

Warns when `mypy.ini` contains unused sections or options, helping catch typos.

**Fails**

```shell
$ mypy --config-file mypy.ini sample_strict.py
mypy.ini:5: error: unused "mypy-nonexistent.*" section  [unused-ignores]
Found 1 error in mypy.ini (errors prevented further checking)
```

```ini
# fragment of mypy.ini
[mypy]
warn_unused_configs = True
[mypy-nonexistent.*]
ignore_errors = True
```

**Passes**

```ini
# fragment of mypy.ini
[mypy]
warn_unused_configs = True
[mypy-tests.*]
ignore_errors = True
```

## warn_redundant_casts = True

Flags casts that do nothing, nudging you to remove dead code.

**Fails**

```shell
$ mypy --config-file mypy.ini sample_redundant_cast.py
sample_redundant_cast.py:4: error: Redundant cast to "str"  [redundant-cast]
```

```python
# sample_redundant_cast.py
from typing import cast

value: str = cast(str, "hello")
```

**Passes**

```python
# sample_redundant_cast.py
value: str = "hello"
```

## warn_unreachable = True

Detects code that can never run.

**Fails**

```shell
$ mypy --config-file mypy.ini sample_unreachable.py
sample_unreachable.py:4: error: Statement in function "divide" is unreachable  [unreachable]
```

```python
# sample_unreachable.py
def divide(a: int, b: int) -> float:
    return a / b
    print("never executes")
```

**Passes**

```python
# sample_unreachable.py
def divide(a: int, b: int) -> float:
    result = a / b
    print(f"result={result}")
    return result
```

## warn_return_any = True

Prevents functions from returning `Any`, forcing you to tighten types.

**Fails**

```shell
$ mypy --config-file mypy.ini sample_return_any.py
sample_return_any.py:5: error: Returning Any from function declared to return "dict"  [return-value]
```

```python
# sample_return_any.py
import json

def load_config(path: str) -> dict:
    return json.loads(open(path).read())
```

**Passes**

```python
# sample_return_any.py
import json
from typing import Any

def load_config(path: str) -> dict[str, Any]:
    with open(path) as fh:
        data = json.load(fh)
    return data
```

## implicit_reexport = False

Stops transitive re-export of imported names unless you re-export explicitly.

**Fails**

```shell
$ mypy --config-file mypy.ini consumer.py
consumer.py:1: error: Module "api" has no attribute "Service"  [attr-defined]
```

```python
# api/__init__.py
from .service import Service  # not re-exported implicitly

# consumer.py
from api import Service
```

**Passes**

```python
# api/__init__.py
from .service import Service

__all__ = ["Service"]

# consumer.py
from api import Service
```

## mypy_path = src, app

Adds `src` and `app` to module search paths so mypy resolves internal packages without configuring `PYTHONPATH`.

**Fails (if `mypy_path` omits `src`)**

```shell
$ mypy --config-file mypy.ini app/main.py
app/main.py:1: error: Cannot find implementation or library stub for module named "util.math"  [import-not-found]
```

```python
# src/util/math.py
def double(x: int) -> int:
    return x * 2

# app/main.py
from util.math import double
```

**Passes (with `mypy_path = src, app`)**

```python
# src/util/math.py
def double(x: int) -> int:
    return x * 2

# app/main.py
from util.math import double
```

## [mypy-tests.*] allow_untyped_defs = True / allow_untyped_calls = True

Relaxes strict mode in test modules so you can write terse fixtures without full annotations.

**Fails (if the override is removed)**

```shell
$ mypy --config-file mypy.ini tests/test_helpers.py
tests/test_helpers.py:1: error: Function is missing a type annotation for argument "()"  [no-untyped-def]
tests/test_helpers.py:4: error: Call to untyped function "build_user" in typed context  [no-untyped-call]
```

```python
# tests/test_helpers.py
def build_user():
    return {"name": "Ada"}

def test_user_defaults():
    user = build_user()
    assert user["name"] == "Ada"
```

**Passes (with the override in place)**

```python
# tests/test_helpers.py
def build_user():
    return {"name": "Ada"}

def test_user_defaults():
    user = build_user()
    assert user["name"] == "Ada"
```

## [mypy-*.migrations.*] ignore_errors = True

Skips type checking for generated migration files that are rarely edited manually.

**Fails (if errors are not ignored)**

```shell
$ mypy --config-file mypy.ini app/users/migrations/0001_initial.py
app/users/migrations/0001_initial.py:3: error: Call to untyped function "get_model" in typed context  [no-untyped-call]
app/users/migrations/0001_initial.py:4: error: Argument 1 to "create" of "Manager" has incompatible type "int"; expected "str"  [arg-type]
```

```python
# app/users/migrations/0001_initial.py
def forwards(apps, schema_editor):
    Model = apps.get_model("users", "User")
    Model.objects.create(name=123)  # type: ignore[call-arg]
```

**Passes (with the ignore rule applied)**

```python
# app/users/migrations/0001_initial.py
def forwards(apps, schema_editor):
    Model = apps.get_model("users", "User")
    Model.objects.create(name=123)
```

## [mypy-*.tests.*] disallow_any_unimported = False / disallow_incomplete_defs = False

Loosens two strict options (enabled via `strict = True`) to accommodate dynamic imports and partially annotated helpers inside `*.tests.*`.

**Fails (if overrides are removed)**

```shell
$ mypy --config-file mypy.ini app/tests/test_imports.py
app/tests/test_imports.py:1: error: Skipping analyzing "pytest": module is installed, but missing library stubs or py.typed marker  [import]
app/tests/test_imports.py:5: error: Function is missing a type annotation for argument "value"  [no-untyped-def]
```

```python
# app/tests/test_imports.py
import pytest

def test_mark():
    @pytest.mark.parametrize("value", [1, 2, 3])
    def inner(value):
        ...
```

**Passes (with the overrides enabled)**

```python
# app/tests/test_imports.py
import pytest

def test_mark():
    @pytest.mark.parametrize("value", [1, 2, 3])
    def inner(value):
        ...
```

## [mypy-some_external_lib.*] ignore_missing_imports = True

Allows you to depend on third-party libraries without stubs. Replace `some_external_lib` with real package names until types are available.

**Fails (if the ignore rule is removed)**

```shell
$ mypy --config-file mypy.ini app/integrations/metrics.py
app/integrations/metrics.py:2: error: Skipping analyzing "some_external_lib": module is not installed or has no type hints  [import]
```

```python
# app/integrations/metrics.py
import some_external_lib

def record() -> None:
    some_external_lib.emit({"count": 1})
```

**Passes (with `ignore_missing_imports = True`)**

```python
# app/integrations/metrics.py
import some_external_lib

def record() -> None:
    some_external_lib.emit({"count": 1})
```

