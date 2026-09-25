from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from django_tolap.drift import drift_warnings_for_body
from django_tolap.models import PolicyAssignment, PolicyAuditLog, PolicyDefinition

pytestmark = pytest.mark.django_db

VALID = {
    "version": "1.0",
    "name": "analyst",
    "permissions": {"canQuery": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {"hiddenFields": ["patients.ssn"]},
    },
}


@pytest.fixture
def admin_client(client):  # type: ignore[no-untyped-def]
    user = get_user_model().objects.create_superuser(username="root", password="x", email="r@x")
    client.force_login(user)
    return client


def test_admin_pages_render(admin_client) -> None:  # type: ignore[no-untyped-def]
    PolicyDefinition.from_body(VALID)
    PolicyAssignment.objects.create(
        policy_id="analyst",
        assignee_type="user",
        assignee_identifier="u",
        granted_by="a",
        reason="r",
    )
    PolicyAuditLog.objects.create(event_type="x", details="d")
    for url in (
        reverse("admin:django_tolap_policydefinition_changelist"),
        reverse("admin:django_tolap_policydefinition_add"),
        reverse("admin:django_tolap_policyassignment_changelist"),
        reverse("admin:django_tolap_policyassignment_add"),
        reverse("admin:django_tolap_policyauditlog_changelist"),
    ):
        assert admin_client.get(url).status_code == 200, url
    changelist = admin_client.get(reverse("admin:django_tolap_policydefinition_changelist"))
    assert b"resolve-preview/" in changelist.content


def test_add_definition_with_invalid_body_shows_error_and_stores_nothing(admin_client) -> None:  # type: ignore[no-untyped-def]
    bad = {
        "version": "1.0",
        "name": "x",
        "permissions": {"canQuery": True},
        "objectRules": {"fieldRules": {"maskedFields": [{"field": "e", "maskType": "rot13"}]}},
    }
    response = admin_client.post(
        reverse("admin:django_tolap_policydefinition_add"),
        {"name": "", "body": json.dumps(bad), "active": "on"},
    )
    assert response.status_code == 200
    assert b"invalid TOLAP policy definition" in response.content
    assert not PolicyDefinition.objects.exists()


def test_add_definition_takes_name_from_body_and_warns_on_drift(admin_client) -> None:  # type: ignore[no-untyped-def]
    body = {
        **VALID,
        "objectRules": {
            "allowedObjects": ["patients"],
            "fieldRules": {"hiddenFields": ["patients.ssn", "patients.nope"]},
        },
    }
    response = admin_client.post(
        reverse("admin:django_tolap_policydefinition_add"),
        {"name": "", "body": json.dumps(body), "active": "on"},
        follow=True,
    )
    assert response.status_code == 200
    assert PolicyDefinition.objects.get().name == "analyst"
    text = response.content.decode()
    assert "Schema drift" in text and "patients.nope" in text and "testapp.Patient" in text


def test_drift_warnings_only_for_targeted_models() -> None:
    assert drift_warnings_for_body(VALID) == []
    warnings = drift_warnings_for_body(
        {
            **VALID,
            "objectRules": {"rowFilters": [{"field": "encounters.missing", "operator": "isNull"}]},
        }
    )
    assert warnings == [
        "encounters: field 'encounters.missing' does not exist on testapp.Encounter"
    ]
    assert drift_warnings_for_body({"version": "1.0"}) == []


def test_admin_saves_and_deletes_are_audited(admin_client) -> None:  # type: ignore[no-untyped-def]
    admin_client.post(
        reverse("admin:django_tolap_policydefinition_add"),
        {"name": "", "body": json.dumps(VALID), "active": "on"},
    )
    definition = PolicyDefinition.objects.get()
    admin_client.post(
        reverse("admin:django_tolap_policyassignment_add"),
        {
            "policy": definition.name,  # FK uses to_field="name"
            "assignee_type": "user",
            "assignee_identifier": "alice",
            "tenant_id": "",
            "source_connection_id": "",
            "active": "on",
            "granted_by": "root",
            "granted_at_0": "2026-01-01",
            "granted_at_1": "00:00:00",
            "reason": "demo",
        },
    )
    assignment = PolicyAssignment.objects.get()
    admin_client.post(
        reverse("admin:django_tolap_policyassignment_delete", args=[assignment.pk]), {"post": "yes"}
    )
    admin_client.post(
        reverse("admin:django_tolap_policydefinition_delete", args=[definition.pk]), {"post": "yes"}
    )
    events = list(PolicyAuditLog.objects.order_by("id").values_list("event_type", flat=True))
    assert events == [
        "definition_created",
        "assignment_saved",
        "assignment_deleted",
        "definition_deleted",
    ]
    assert all(e.user_id for e in PolicyAuditLog.objects.all())


def test_resolve_preview_reports_resolution_errors(admin_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from django_tolap import admin as admin_module

    def boom(self, *a, **k):  # type: ignore[no-untyped-def]
        raise ValueError("bad assignment")

    monkeypatch.setattr(admin_module.DjangoPolicyStore, "resolve_policy", boom)
    response = admin_client.post(
        reverse("admin:django_tolap_resolve_preview"),
        {"user_id": "alice", "tenant_id": "t", "source_connection_id": "db:x:y"},
    )
    assert response.status_code == 200 and b"resolution failed" in response.content


def test_audit_log_is_read_only(admin_client) -> None:  # type: ignore[no-untyped-def]
    assert admin_client.get(reverse("admin:django_tolap_policyauditlog_add")).status_code == 403


def test_resolve_preview(admin_client) -> None:  # type: ignore[no-untyped-def]
    PolicyDefinition.from_body({**VALID, "limits": {"maxResults": 42}})
    PolicyAssignment.objects.create(
        policy_id="analyst",
        assignee_type="user",
        assignee_identifier="alice",
        granted_by="a",
        reason="r",
    )
    url = reverse("admin:django_tolap_resolve_preview")
    assert admin_client.get(url).status_code == 200
    response = admin_client.post(
        url, {"user_id": "alice", "tenant_id": "t", "source_connection_id": "db:x:patients"}
    )
    assert response.status_code == 200
    text = response.content.decode()  # JSON is HTML-escaped inside <pre>
    assert "&quot;maxResults&quot;: 42" in text and "&quot;sourceProfiles&quot;" in text
    assert "analyst" in text
    assert not PolicyAuditLog.objects.filter(event_type="policy_resolved").exists()


def test_admin_bulk_delete_action_audits_every_definition(admin_client) -> None:  # type: ignore[no-untyped-def]
    names = ["bulk-a", "bulk-b"]
    for name in names:
        PolicyDefinition.from_body({**VALID, "name": name})
    admin_client.post(
        reverse("admin:django_tolap_policydefinition_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": list(PolicyDefinition.objects.values_list("pk", flat=True)),
            "post": "yes",
        },
    )
    assert not PolicyDefinition.objects.exists()
    deleted = PolicyAuditLog.objects.filter(event_type="definition_deleted")
    assert sorted(deleted.values_list("policy_name", flat=True)) == names
