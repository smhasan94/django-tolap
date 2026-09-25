from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from tolap_core import deserialize_policy_assignment, deserialize_policy_definition, serialize

from django_tolap.models import PolicyAssignment, PolicyAuditLog, PolicyDefinition
from tests.harness.fixtures import UPSTREAM

pytestmark = pytest.mark.django_db

VALID_POLICIES = sorted(
    p for p in (UPSTREAM / "policies").glob("*.json") if "invalid" not in p.name
)
INVALID_POLICIES = sorted(p for p in (UPSTREAM / "policies").glob("invalid-*.json"))
ASSIGNMENTS = sorted((UPSTREAM / "assignments").glob("*.json"))


@pytest.mark.parametrize("path", VALID_POLICIES, ids=lambda p: p.name)
def test_definition_round_trips_fixture(path) -> None:  # type: ignore[no-untyped-def]
    body = json.loads(path.read_text())
    stored = PolicyDefinition.from_body(body)
    assert stored.name == body["name"]
    assert serialize(stored.to_upstream()) == serialize(deserialize_policy_definition(body))
    assert stored.description == (body.get("description") or "")
    assert stored.priority == body.get("priority")


@pytest.mark.parametrize("path", INVALID_POLICIES, ids=lambda p: p.name)
def test_invalid_fixture_rejected(path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        PolicyDefinition.from_body(json.loads(path.read_text()))
    assert not PolicyDefinition.objects.exists()


def test_name_must_match_body() -> None:
    d = PolicyDefinition(
        name="other", body={"version": "1.0", "name": "x", "permissions": {"canQuery": True}}
    )
    with pytest.raises(ValidationError) as exc:
        d.full_clean()
    assert "name" in exc.value.message_dict


def test_body_must_be_object() -> None:
    with pytest.raises(ValidationError):
        PolicyDefinition(name="x", body=["nope"]).full_clean()


@pytest.mark.parametrize("path", ASSIGNMENTS, ids=lambda p: p.name)
def test_assignment_round_trips_fixture(path) -> None:  # type: ignore[no-untyped-def]
    raw = json.loads(path.read_text())
    upstream = deserialize_policy_assignment(raw)
    PolicyDefinition.from_body(
        {"version": "1.0", "name": upstream.policy_name, "permissions": {"canQuery": True}}
    )
    stored = PolicyAssignment.from_upstream(upstream)
    assert serialize(stored.to_upstream()) == serialize(upstream)


def test_unscoped_assignment_uses_empty_strings_and_maps_to_none() -> None:
    PolicyDefinition.from_body({"version": "1.0", "name": "p", "permissions": {"canQuery": True}})
    a = PolicyAssignment.objects.create(
        policy_id="p", assignee_type="user", assignee_identifier="u", granted_by="admin", reason="r"
    )
    assert a.tenant_id == "" and a.source_connection_id == ""
    up = a.to_upstream()
    assert up.scope.tenant_id is None and up.scope.source_connection_id is None
    assert up.audit.granted_at.endswith("Z")


def test_assignment_unique_per_scope() -> None:
    from django.db import IntegrityError

    PolicyDefinition.from_body({"version": "1.0", "name": "p", "permissions": {"canQuery": True}})
    kwargs = dict(
        policy_id="p", assignee_type="user", assignee_identifier="u", granted_by="a", reason="r"
    )
    PolicyAssignment.objects.create(**kwargs)
    PolicyAssignment.objects.create(**kwargs, tenant_id="t")
    with pytest.raises(IntegrityError):
        PolicyAssignment.objects.create(**kwargs)


def test_audit_log_str() -> None:
    event = PolicyAuditLog.objects.create(
        event_type="definition_created", details="x", timestamp=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert "definition_created" in str(event)
