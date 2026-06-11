"""Application-level error taxonomy.

Define the root exception ``AppError`` here. All domain-specific errors
derive from it so callers can catch ``AppError`` to handle any known failure.
"""

from __future__ import annotations


class AppError(Exception):
    """Root exception for all application-level errors."""


class ItemizationError(AppError):
    """Raised when itemization inputs are invalid."""
