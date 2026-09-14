"""Domain exceptions for the budget app.

Each carries a user-facing hint so the CLI can print
"[오류] ...\n[힌트] ..." without ever showing a stack trace.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all expected, user-facing errors."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ValidationError(AppError):
    """Raised when user input fails validation."""


class NotFoundError(AppError):
    """Raised when a referenced record (transaction/category/budget) is missing."""


class ConflictError(AppError):
    """Raised when an operation would violate a data integrity rule."""
