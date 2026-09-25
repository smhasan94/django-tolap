"""TOLAP policy definitions and assignments as Django models.

The definition body is the upstream JSON document verbatim (validated through upstream's
own deserializer on ``clean()``), with a few columns denormalized for the admin. Assignments
are columns because they are what resolution filters on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from tolap_core import (
    Assignee,
    AssigneeType,
    AssignmentScope,
    AuditInfo,
    deserialize_policy_definition,
)
from tolap_core import (
    PolicyAssignment as UpstreamAssignment,
)
from tolap_core import (
    PolicyDefinition as UpstreamDefinition,
)

ASSIGNEE_TYPES = [(t.value, t.value) for t in AssigneeType]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class PolicyDefinition(models.Model):
    name = models.CharField(max_length=128, unique=True)
    body = models.JSONField(help_text="The TOLAP policy definition (schema v1.0), verbatim.")
    description = models.TextField(blank=True, default="")
    priority = models.IntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "TOLAP policy definition"

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if not isinstance(self.body, dict):
            raise ValidationError({"body": "must be a JSON object"})
        try:
            upstream = deserialize_policy_definition(self.body)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValidationError({"body": f"invalid TOLAP policy definition: {exc!r}"}) from exc
        if not self.name:
            self.name = upstream.name
        elif upstream.name != self.name:
            raise ValidationError({"name": "must equal body['name']"})
        self.description = upstream.description or ""
        self.priority = upstream.priority

    def to_upstream(self) -> UpstreamDefinition:
        return deserialize_policy_definition(self.body)

    @classmethod
    def from_body(cls, body: dict[str, Any], *, active: bool = True) -> PolicyDefinition:
        instance = cls(name=str(body.get("name", "")), body=body, active=active)
        instance.full_clean()
        instance.save()
        return instance


class PolicyAssignment(models.Model):
    policy = models.ForeignKey(
        PolicyDefinition, to_field="name", on_delete=models.CASCADE, related_name="assignments"
    )
    assignee_type = models.CharField(max_length=32, choices=ASSIGNEE_TYPES)
    assignee_identifier = models.CharField(max_length=255)
    # 128, not 255: the unique constraint below spans five string columns and MySQL caps an
    # InnoDB key at 3072 bytes (768 utf8mb4 characters). 128+32+255+128+128 = 671.
    tenant_id = models.CharField(max_length=128, blank=True, default="", help_text="Empty = any")
    source_connection_id = models.CharField(
        max_length=128, blank=True, default="", help_text="Empty = any"
    )
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.CharField(max_length=255)
    granted_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField()

    class Meta:
        ordering = ["policy__name", "assignee_type", "assignee_identifier"]
        verbose_name = "TOLAP policy assignment"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "policy",
                    "assignee_type",
                    "assignee_identifier",
                    "tenant_id",
                    "source_connection_id",
                ],
                name="django_tolap_assignment_unique",
            )
        ]
        indexes = [
            models.Index(fields=["assignee_type", "assignee_identifier"]),
            models.Index(fields=["tenant_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.policy_id} -> {self.assignee_type}:{self.assignee_identifier}"

    def to_upstream(self) -> UpstreamAssignment:
        return UpstreamAssignment(
            version="1.0",
            policy_name=str(self.policy_id),
            assignee=Assignee(
                type=AssigneeType(self.assignee_type), identifier=self.assignee_identifier
            ),
            scope=AssignmentScope(
                tenant_id=self.tenant_id or None,
                source_connection_id=self.source_connection_id or None,
            ),
            active=self.active,
            audit=AuditInfo(
                granted_by=self.granted_by,
                granted_at=_iso(self.granted_at) or "",
                reason=self.reason,
            ),
            expires_at=_iso(self.expires_at),
            revoked_at=_iso(self.revoked_at),
        )

    @classmethod
    def from_upstream(cls, assignment: UpstreamAssignment) -> PolicyAssignment:
        instance = cls(
            policy_id=assignment.policy_name,
            assignee_type=assignment.assignee.type.value,
            assignee_identifier=assignment.assignee.identifier,
            tenant_id=assignment.scope.tenant_id or "",
            source_connection_id=assignment.scope.source_connection_id or "",
            active=assignment.active,
            expires_at=_parse_iso(assignment.expires_at),
            revoked_at=_parse_iso(assignment.revoked_at),
            granted_by=assignment.audit.granted_by,
            granted_at=_parse_iso(assignment.audit.granted_at) or timezone.now(),
            reason=assignment.audit.reason,
        )
        instance.save()
        return instance


class PolicyAuditLog(models.Model):
    """One row per store event, with upstream ``PolicyAuditEvent`` fields."""

    event_type = models.CharField(max_length=64)
    timestamp = models.DateTimeField(default=timezone.now)
    details = models.TextField()
    user_id = models.CharField(max_length=255, null=True, blank=True)
    policy_name = models.CharField(max_length=128, null=True, blank=True)
    assignee_identifier = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        verbose_name = "TOLAP audit event"

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} {self.event_type}"
