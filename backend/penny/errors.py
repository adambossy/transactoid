"""Application-level error taxonomy.

Define the root exception ``AppError`` here. All domain-specific errors
derive from it so callers can catch ``AppError`` to handle any known failure.
"""

from __future__ import annotations


class AppError(Exception):
    """Root exception for all application-level errors."""


class ItemizationError(AppError):
    """Raised when itemization inputs are invalid."""


class SplitError(AppError):
    """Raised when a split_transaction operation cannot proceed.

    Covers validation failures (verified row, Amazon gating, bad amounts)
    and integrity errors caught during the atomic write.
    """


class RefundError(AppError):
    """Raised when a record_refund operation cannot proceed.

    Covers validation failures (transaction not found, verified row,
    already linked, pre-date violation, currency mismatch) and integrity
    errors caught during the atomic write.
    """
