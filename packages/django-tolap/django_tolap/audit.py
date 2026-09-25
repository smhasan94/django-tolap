"""Record store events in ``PolicyAuditLog`` (upstream ``PolicyAuditEvent`` fields)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from tolap_store import PolicyAuditEvent

from django_tolap.models import PolicyAuditLog


def record(
    event: PolicyAuditEvent,
    *,
    to_db: bool = True,
    callback: Callable[[PolicyAuditEvent], None] | None = None,
) -> None:
    if to_db:
        PolicyAuditLog.objects.create(
            event_type=event.event_type,
            timestamp=datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")),
            details=event.details,
            user_id=event.user_id,
            policy_name=event.policy_name,
            assignee_identifier=event.assignee_identifier,
        )
    if callback is not None:
        callback(event)


def definition_event(name: str, action: str, *, actor: str | None = None) -> PolicyAuditEvent:
    return PolicyAuditEvent.create(
        event_type=f"definition_{action}",
        details=f"Policy definition '{name}' {action}" + (f" by {actor}" if actor else ""),
        policy_name=name,
        user_id=actor,
    )


def assignment_event(
    policy_name: str, identifier: str, action: str, *, actor: str | None = None
) -> PolicyAuditEvent:
    return PolicyAuditEvent.create(
        event_type=f"assignment_{action}",
        details=f"Assignment for policy '{policy_name}' to '{identifier}' {action}"
        + (f" by {actor}" if actor else ""),
        policy_name=policy_name,
        assignee_identifier=identifier,
        user_id=actor,
    )
