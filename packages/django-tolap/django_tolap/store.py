"""``DjangoPolicyStore``: upstream's ``PolicyStore`` protocol on the Django models.

Resolution is delegated to ``tolap_core.resolve`` -- the merge, scope, expiry and
revocation rules are upstream's. This store only answers "which definitions and assignments
exist" (from the database) and "which groups and roles does this user hold" (from the
identity resolver), then records an audit event.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from tolap_core import (
    EffectivePolicy,
    resolve,
    serialize,
)
from tolap_core import (
    PolicyAssignment as UpstreamAssignment,
)
from tolap_core import (
    PolicyDefinition as UpstreamDefinition,
)
from tolap_store import IdentityResolver, PolicyAuditEvent

from django_tolap.identity import load_identity_resolver
from django_tolap.models import PolicyAssignment, PolicyAuditLog, PolicyDefinition

if TYPE_CHECKING:
    from tolap_store import PolicyStore


class DjangoPolicyStore:
    def __init__(
        self,
        identity_resolver: IdentityResolver | None = None,
        on_audit: Callable[[PolicyAuditEvent], None] | None = None,
        *,
        audit_to_db: bool = True,
    ) -> None:
        self._identity = identity_resolver or load_identity_resolver()
        self._on_audit = on_audit
        self._audit_to_db = audit_to_db

    # -- audit --

    def _emit(self, event: PolicyAuditEvent) -> None:
        if self._audit_to_db:
            PolicyAuditLog.objects.create(
                event_type=event.event_type,
                timestamp=datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")),
                details=event.details,
                user_id=event.user_id,
                policy_name=event.policy_name,
                assignee_identifier=event.assignee_identifier,
            )
        if self._on_audit is not None:
            self._on_audit(event)

    # -- definitions --

    def get_definition(self, name: str) -> UpstreamDefinition | None:
        row = PolicyDefinition.objects.filter(name=name, active=True).first()
        return row.to_upstream() if row else None

    def list_definitions(self) -> list[UpstreamDefinition]:
        return [row.to_upstream() for row in PolicyDefinition.objects.filter(active=True)]

    def save_definition(self, definition: UpstreamDefinition) -> None:
        body: dict[str, Any] = json.loads(serialize(definition))
        self.save_definition_json(body)

    def save_definition_json(
        self, body: dict[str, Any], *, active: bool = True
    ) -> PolicyDefinition:
        """Validate ``body`` through upstream's deserializer and create or update the row."""
        name = str(body.get("name", ""))
        with transaction.atomic():
            existing = PolicyDefinition.objects.filter(name=name).first()
            if existing is None:
                row = PolicyDefinition.from_body(body, active=active)
                event = "definition_created"
            else:
                existing.body = body
                existing.active = active
                existing.full_clean()
                existing.save()
                row = existing
                event = "definition_updated"
            self._emit(
                PolicyAuditEvent.create(
                    event_type=event,
                    details=f"Policy definition '{row.name}' {event.split('_')[1]}",
                    policy_name=row.name,
                )
            )
        return row

    def delete_definition(self, name: str) -> bool:
        with transaction.atomic():
            deleted, _ = PolicyDefinition.objects.filter(name=name).delete()
            if deleted:
                self._emit(
                    PolicyAuditEvent.create(
                        event_type="definition_deleted",
                        details=f"Policy definition '{name}' deleted",
                        policy_name=name,
                    )
                )
        return bool(deleted)

    # -- assignments --

    def _assignment_rows(self, user_id: str, tenant_id: str) -> Any:
        """Rows that could apply: assignee matches, tenant matches, currently in force.

        Upstream ``resolve`` re-applies the active/expiry/revocation rules; this filter is
        defence in depth and keeps the query small.
        """
        now = timezone.now()
        assignee = Q(assignee_type__in=["user", "serviceAccount"], assignee_identifier=user_id)
        groups = self._identity.get_groups(user_id)
        if groups:
            assignee |= Q(assignee_type="group", assignee_identifier__in=groups)
        roles = self._identity.get_roles(user_id)
        if roles:
            assignee |= Q(assignee_type="role", assignee_identifier__in=roles)
        return (
            PolicyAssignment.objects.filter(assignee, active=True)
            .filter(Q(tenant_id="") | Q(tenant_id=tenant_id))
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .filter(Q(revoked_at__isnull=True) | Q(revoked_at__gt=now))
        )

    def get_assignments(self, user_id: str, tenant_id: str) -> list[UpstreamAssignment]:
        return [row.to_upstream() for row in self._assignment_rows(user_id, tenant_id)]

    def save_assignment(self, assignment: UpstreamAssignment) -> None:
        """Create or replace, keyed like upstream's in-memory store on (policy, identifier)."""
        with transaction.atomic():
            PolicyAssignment.objects.filter(
                policy__name=assignment.policy_name,
                assignee_identifier=assignment.assignee.identifier,
            ).delete()
            PolicyAssignment.from_upstream(assignment)
            self._emit(
                PolicyAuditEvent.create(
                    event_type="assignment_saved",
                    details=(
                        f"Assignment for policy '{assignment.policy_name}' to "
                        f"'{assignment.assignee.identifier}' saved"
                    ),
                    policy_name=assignment.policy_name,
                    assignee_identifier=assignment.assignee.identifier,
                )
            )

    def delete_assignment(self, policy_name: str, assignee_identifier: str) -> bool:
        with transaction.atomic():
            deleted, _ = PolicyAssignment.objects.filter(
                policy__name=policy_name, assignee_identifier=assignee_identifier
            ).delete()
            if deleted:
                self._emit(
                    PolicyAuditEvent.create(
                        event_type="assignment_deleted",
                        details=(
                            f"Assignment for policy '{policy_name}' to "
                            f"'{assignee_identifier}' deleted"
                        ),
                        policy_name=policy_name,
                        assignee_identifier=assignee_identifier,
                    )
                )
        return bool(deleted)

    def assign(
        self,
        policy_name: str,
        *,
        user_id: str | None = None,
        group: str | None = None,
        role: str | None = None,
        service_account: str | None = None,
        tenant_id: str | None = None,
        source: str | None = None,
        granted_by: str,
        reason: str,
        expires_at: datetime | None = None,
    ) -> PolicyAssignment:
        """Convenience: create one assignment row for exactly one assignee."""
        choices = {
            "user": user_id,
            "group": group,
            "role": role,
            "serviceAccount": service_account,
        }
        chosen = [(t, i) for t, i in choices.items() if i]
        if len(chosen) != 1:
            raise ValueError("assign() takes exactly one of user_id, group, role, service_account")
        assignee_type, identifier = chosen[0]
        with transaction.atomic():
            row = PolicyAssignment.objects.create(
                policy_id=policy_name,
                assignee_type=assignee_type,
                assignee_identifier=identifier,
                tenant_id=tenant_id or "",
                source_connection_id=source or "",
                granted_by=granted_by,
                reason=reason,
                expires_at=expires_at,
            )
            self._emit(
                PolicyAuditEvent.create(
                    event_type="assignment_saved",
                    details=f"Assignment for policy '{policy_name}' to '{identifier}' saved",
                    policy_name=policy_name,
                    assignee_identifier=identifier,
                )
            )
        return row

    # -- resolution --

    def resolve_policy(
        self,
        user_id: str,
        tenant_id: str,
        source_connection_id: str,
        *,
        declared_purpose: str | None = None,
    ) -> EffectivePolicy:
        if declared_purpose is not None:
            # tolap-core 1.0.0 has no purpose binding. Ignoring a declared purpose would
            # resolve a policy nobody asked for (upstream's own words), so refuse.
            raise NotImplementedError("purpose binding requires tolap-core >= 1.1")
        result = resolve(
            user_id=user_id,
            tenant_id=tenant_id,
            source_connection_id=source_connection_id,
            assignments=self.get_assignments(user_id, tenant_id),
            definitions={d.name: d for d in self.list_definitions()},
            get_groups=self._identity.get_groups,
            get_roles=self._identity.get_roles,
        )
        self._emit(
            PolicyAuditEvent.create(
                event_type="policy_resolved",
                details=(
                    f"Policy resolved for user '{user_id}' in tenant '{tenant_id}' "
                    f"for source '{source_connection_id}'"
                ),
                user_id=user_id,
            )
        )
        return result


if TYPE_CHECKING:
    _conforms: PolicyStore = DjangoPolicyStore()
