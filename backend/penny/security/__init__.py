"""Security primitives — currently the read-only SQL guard.

Standalone, Penny-agnostic modules that harden the boundary between the
LLM-driven agent and the database. See :mod:`penny.security.sql_read_guard`.
"""

from penny.security.sql_read_guard import (
    SqlGuardError,
    assert_read_only_select,
    is_read_only_select,
)

__all__ = [
    "SqlGuardError",
    "assert_read_only_select",
    "is_read_only_select",
]
