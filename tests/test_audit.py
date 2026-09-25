from __future__ import annotations

import pytest
from tolap_store import PolicyAuditEvent, StaticIdentityResolver

from django_tolap.models import PolicyAuditLog
from django_tolap.store import DjangoPolicyStore

pytestmark = pytest.mark.django_db


def test_every_store_mutation_and_resolve_is_audited() -> None:
    seen: list[PolicyAuditEvent] = []
    store = DjangoPolicyStore(
        identity_resolver=StaticIdentityResolver({}, {}), on_audit=seen.append
    )
    store.save_definition_json({"version": "1.0", "name": "p", "permissions": {"canQuery": True}})
    store.save_definition_json({"version": "1.0", "name": "p", "permissions": {"canQuery": True}})
    store.assign("p", user_id="alice", granted_by="admin", reason="demo")
    store.resolve_policy("alice", "t", "db:x:y")
    store.delete_assignment("p", "alice")
    store.delete_definition("p")
    events = list(PolicyAuditLog.objects.order_by("id").values_list("event_type", flat=True))
    assert events == [
        "definition_created",
        "definition_updated",
        "assignment_saved",
        "policy_resolved",
        "assignment_deleted",
        "definition_deleted",
    ]
    assert [e.event_type for e in seen] == events
    resolved = PolicyAuditLog.objects.get(event_type="policy_resolved")
    assert resolved.user_id == "alice"
    assert PolicyAuditLog.objects.get(event_type="assignment_saved").assignee_identifier == "alice"


def test_audit_to_db_can_be_disabled() -> None:
    store = DjangoPolicyStore(identity_resolver=StaticIdentityResolver({}, {}), audit_to_db=False)
    store.save_definition_json({"version": "1.0", "name": "p", "permissions": {"canQuery": True}})
    assert not PolicyAuditLog.objects.exists()
