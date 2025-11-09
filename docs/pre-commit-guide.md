# Pre-commit Hook Guide

> This document must stay in lock-step with `.pre-commit-config.yaml`. When you update the configuration, update this guide so that future editors (humans or LLMs) can understand why each hook exists and how to exercise it.

## default_language_version

Ensures Python hooks run under Python 3.12 so tooling can leverage the same language level as the project.

**Fails (tool auth errors under older Python)**

```shell
$ python3.10 -m ruff check sample_pattern.py
sample_pattern.py:1:1: F401 `typing.Self` imported but unused
sample_pattern.py:1:1: error: cannot import name 'Self' from 'typing' (Python 3.10 has it as typing_extensions.Self)
```

```python
# sample_pattern.py
from typing import Self

class Builder:
    def set_name(self, name: str) -> Self:
        self._name = name
        return self
```

**Passes (hooks run with Python 3.12)**

```shell
$ python3.12 -m ruff check sample_pattern.py
$ echo $?  # ruff exits 0 after the warning is fixed
0
```

```python
# sample_pattern.py
from typing import Self

class Builder:
    def set_name(self, name: str) -> Self:
        self._name = name
        return self
```

## check-added-large-files

Prevents accidentally committing bulky data or binary blobs. The hook is configured to block files larger than ~512 KB.

**Fails**

```shell
$ dd if=/dev/zero of=big_dump.bin bs=1k count=800
$ git add big_dump.bin
$ pre-commit run check-added-large-files
check-added-large-files.................................................Failed
- hook id: check-added-large-files
- duration: 0.05s
- files were modified by this hook
big_dump.bin (819200B) exceeds maximum size of 524288B
```

**Passes**

```shell
$ truncate -s 128k big_dump.bin  # shrink the file
$ pre-commit run check-added-large-files
check-added-large-files.................................................Passed
```

## check-merge-conflict

Blocks files that still contain Git conflict markers.

**Fails**

```text
<<<<<<< HEAD
print("feature")
=======
print("main")
>>>>>>> origin/main
```

```shell
$ pre-commit run check-merge-conflict
check-merge-conflict....................................................Failed
- hook id: check-merge-conflict
- exit code: 1
docs/example.md: Contains conflict marker
```

**Passes**

```python
# docs/example.md
print("feature")
```

```shell
$ pre-commit run check-merge-conflict
check-merge-conflict....................................................Passed
```

## end-of-file-fixer

Normalizes files so they end with a single newline character, which avoids noisy diffs.

**Fails (missing trailing newline)**

```text
# sample_eof.py (no trailing newline)
print("Hello world")
```

```shell
$ pre-commit run end-of-file-fixer
end-of-file-fixer.......................................................Failed
- hook id: end-of-file-fixer
- files were modified by this hook
```

**Passes**

```python
# sample_eof.py
print("Hello world")
```

```shell
$ pre-commit run end-of-file-fixer
end-of-file-fixer.......................................................Passed
```

## trailing-whitespace

Strips stray spaces at line ends. The Markdown exception preserves intentional hard breaks.

**Fails**

```text
# sample_trailing_whitespace.py (note the trailing spaces after the colon and quote)
def greet(name: str) -> str: 
    return f"Hello {name}" 
```

```shell
$ pre-commit run trailing-whitespace
trailing-whitespace.....................................................Failed
- hook id: trailing-whitespace
- files were modified by this hook
```

**Passes**

```python
# sample_trailing_whitespace.py
def greet(name: str) -> str:
    return f"Hello {name}"
```

```shell
$ pre-commit run trailing-whitespace
trailing-whitespace.....................................................Passed
```

## ruff

Applies the Ruff linter, enforcing the policies from `ruff.toml`.

**Fails**

```python
# sample_ruff.py
import json

def load(path: str) -> dict:
    config = json.load(open(path))
    return config
```

```shell
$ pre-commit run ruff
ruff....................................................................Failed
- hook id: ruff
- exit code: 1
sample_ruff.py:1:1: F401 `json` imported but unused
sample_ruff.py:4:21: B301 Use `with open()` to ensure files are closed promptly
```

**Passes**

```python
# sample_ruff.py
from __future__ import annotations

import json
from pathlib import Path

def load(path: str) -> dict:
    with Path(path).open() as fh:
        return json.load(fh)
```

```shell
$ pre-commit run ruff
ruff....................................................................Passed
```

## ruff-format

Runs Ruff’s formatter to keep layout consistent.

**Fails (unformatted input triggers rewrite)**

```python
# sample_ruff_format.py
def add(a:int,b:int)->int:
 return a + b
```

```shell
$ pre-commit run ruff-format
ruff-format.............................................................Failed
- hook id: ruff-format
- files were modified by this hook
```

**Passes (formatted to Ruff style)**

```python
# sample_ruff_format.py
def add(a: int, b: int) -> int:
    return a + b
```

```shell
$ pre-commit run ruff-format
ruff-format.............................................................Passed
```

## mypy

Runs the strict type checker before commits, catching regressions described in `docs/mypy-guide.md`.

**Fails**

```python
# sample_mypy.py
def greet(name):
    return "hi " + name
```

```shell
$ pre-commit run mypy
mypy.....................................................................Failed
- hook id: mypy
sample_mypy.py:1: error: Function is missing a type annotation for argument "name"  [no-untyped-def]
sample_mypy.py:1: error: Function is missing a return type annotation  [no-untyped-def]
```

**Passes**

```python
# sample_mypy.py
def greet(name: str) -> str:
    return "hi " + name
```

```shell
$ pre-commit run mypy
mypy.....................................................................Passed
```

