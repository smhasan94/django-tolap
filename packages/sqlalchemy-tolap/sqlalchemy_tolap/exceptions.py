"""Exceptions raised by sqlalchemy-tolap. Messages carry a reason, never row data."""

from __future__ import annotations


class TolapDenied(PermissionError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Access denied: {reason}")
        self.reason = reason


class Uninspectable(TolapDenied):
    def __init__(self, why: str) -> None:
        super().__init__(f"query cannot be inspected: {why}")
        self.why = why
