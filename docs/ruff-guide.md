# Ruff Configuration Guide

> This document must stay in lock-step with `ruff.toml`. When you tweak the configuration, update this guide so editors (humans or LLMs) understand the rationale and can generate code that satisfies the current rules.

## line-length = 88

Sets Ruff’s formatter and E501 checker to match Black’s 88-column limit.

**Without the directive (line runs long)**

```python
# demo_line_length.py
message = "User {name} triggered a webhook with payload {payload} at {timestamp}, ensure we log it precisely."
```

**With the directive (line wrapped to respect 88 characters)**

```python
# demo_line_length.py
message = (
    "User {name} triggered a webhook with payload {payload} at {timestamp}, "
    "ensure we log it precisely."
)
```

## target-version = "py311"

Lets Ruff (and especially the `UP` rules) assume Python 3.11 features are available.

**Without the directive (must fall back to `typing_extensions.Self`)**

```python
from typing_extensions import Self

class Repository:
    def set_name(self, name: str) -> Self:
        self._name = name
        return self
```

**With the directive (can use the stdlib `typing.Self`)**

```python
from typing import Self

class Repository:
    def set_name(self, name: str) -> Self:
        self._name = name
        return self
```

## extend-select

Turns on additional lint families (`B`, `C4`, `E`, `F`, `I`, `N`, `S`, `TID`, `UP`, `W`). The example below highlights one of the extra checks (`B006` from flake8-bugbear) catching mutable defaults.

**Without the directive (mutable default slips through)**

```python
# demo_extend_select.py
def append_user(user, cache=[]):
    cache.append(user)
    return cache
```

**With the directive (must avoid mutable default to satisfy bugbear)**

```python
# demo_extend_select.py
from typing import Optional

def append_user(user, cache: Optional[list] = None):
    if cache is None:
        cache = []
    cache.append(user)
    return cache
```

## ignore

Suppresses selected rules so the code style stays compatible with existing formatting choices.

### ignore = ["E203"]

Allows slice spacing that Black prefers (`result[1 : 3]`).

**Without the ignore (Ruff flags the space before `:`)**

```python
numbers = [1, 2, 3, 4]
subset = numbers[1 : 3]
```

**With the ignore (Black-style slice passes)**

```python
numbers = [1, 2, 3, 4]
subset = numbers[1 : 3]
```

### ignore = ["E266"]

Permits section headers with multiple `#` characters.

**Without the ignore (extra hashes rejected)**

```python
## TODO: remove legacy endpoints
def remove_legacy() -> None:
    ...
```

**With the ignore (decorative comment allowed)**

```python
## TODO: remove legacy endpoints
def remove_legacy() -> None:
    ...
```

### ignore = ["B905"]

Stops bugbear from demanding `strict=True` on every `zip()` call—handy when targeting Python 3.11 where the default is often good enough.

**Without the ignore (Bugbear forces `strict=True`)**

```python
pairs = list(zip(user_ids, user_names))  # B905: `zip` without strict=...
```

**With the ignore (plain `zip` accepted)**

```python
pairs = list(zip(user_ids, user_names))
```

## tests/** = ["S101"]

Allows bare `assert` statements inside test modules despite the Bandit (`S101`) warning.

**Without the per-file ignore (Bandit blocks `assert`)**

```python
# tests/test_profile.py
def test_profile_defaults():
    profile = build_profile()
    assert profile["plan"] == "free"  # S101
```

**With the per-file ignore (assert is fine in tests)**

```python
# tests/test_profile.py
def test_profile_defaults():
    profile = build_profile()
    assert profile["plan"] == "free"
```

## known-first-party = ["your_package"]

Instructs Ruff’s isort engine to treat `your_package` as first-party so imports land in the correct section.

**Without the directive (isort groups it with third-party libraries)**

```python
# demo_known_first_party.py
import requests
from your_package.api import create_user
```

**With the directive (first-party imports sit in their own block)**

```python
# demo_known_first_party.py
import requests

from your_package.api import create_user
```

## combine-as-imports = true

Keeps multiple alias imports combined on one line instead of splitting them.

**Without the directive (aliases split apart)**

```python
import os as operating_system
import sys as system
```

**With the directive (aliases combined for readability)**

```python
import os as operating_system, sys as system
```

## force-sort-within-sections = true

Ensures `from ... import ...` members stay alphabetized, even when they’re already in the same section.

**Without the directive (member order left as-written)**

```python
from your_package.models import User, Account, AuditLog
```

**With the directive (members sorted alphabetically)**

```python
from your_package.models import Account, AuditLog, User
```

