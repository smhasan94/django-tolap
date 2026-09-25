"""Exceptions raised by django-tolap. Messages carry a reason, never row data."""

from __future__ import annotations


class TolapDenied(PermissionError):
    """A query or tool call was refused. ``reason`` is the upstream-style reason string."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Access denied: {reason}")
        self.reason = reason


class TolapSchemaMismatch(TolapDenied):
    """The policy references a field or object the Django model does not have."""


class Uninspectable(TolapDenied):
    """The QuerySet contains a construct whose referenced columns cannot be determined."""

    def __init__(self, why: str) -> None:
        super().__init__(f"query cannot be inspected: {why}")
        self.why = why
