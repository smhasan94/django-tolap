"""``manage.py tolap_resolve``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from django_tolap import accept_context
from django_tolap.models import PolicyAuditLog
from django_tolap.store import DjangoPolicyStore
from tests.test_enforce import ANALYST

pytestmark = pytest.mark.django_db


@pytest.fixture
def assigned() -> DjangoPolicyStore:
    store = DjangoPolicyStore(audit_to_db=False)
    store.save_definition_json({"version": "1.0", "name": "analyst", **ANALYST})
    store.assign(
        "analyst", user_id="alice", tenant_id="clinic", granted_by="test", reason="fixture"
    )
    return store


def run(*args: str) -> str:
    out = StringIO()
    call_command("tolap_resolve", *args, stdout=out)
    return out.getvalue()


def test_prints_effective_policy_json(assigned: DjangoPolicyStore) -> None:
    policy = json.loads(run("alice", "--tenant", "clinic", "--source", "db:clinic:patients"))
    assert policy["permissions"]["canQuery"] is True
    assert policy["objectRules"]["allowedObjects"] == ["patients"]
    assert policy["userId"] == "alice" and policy["tenantId"] == "clinic"
    assert not PolicyAuditLog.objects.exists()  # a preview is not a grant


def test_unassigned_user_resolves_to_deny_all(assigned: DjangoPolicyStore) -> None:
    policy = json.loads(run("mallory", "--tenant", "clinic"))
    assert policy["permissions"]["canQuery"] is False


def test_assignments_listed(assigned: DjangoPolicyStore) -> None:
    doc = json.loads(run("alice", "--tenant", "clinic", "--assignments"))
    assert doc["assignments"] == [
        {
            "policy": "analyst",
            "assignee": "user:alice",
            "tenant": "clinic",
            "source": None,
            "expiresAt": None,
        }
    ]
    assert doc["policy"]["permissions"]["canQuery"] is True


def test_context_is_signed_and_accepted(assigned: DjangoPolicyStore) -> None:
    wire = run(
        "alice", "--tenant", "clinic", "--source", "db:clinic:patients", "--context", "--ttl", "60"
    ).strip()
    context = accept_context(wire)
    assert context.effective_policy.object_rules is not None
    assert context.effective_policy.object_rules.allowed_objects == ["patients"]


def test_audit_flag_records_resolution(assigned: DjangoPolicyStore) -> None:
    run("alice", "--tenant", "clinic", "--audit")
    assert list(PolicyAuditLog.objects.values_list("event_type", flat=True)) == ["policy_resolved"]


def test_resolution_failure_is_a_command_error(assigned: DjangoPolicyStore, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(self, *a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("store down")

    monkeypatch.setattr(DjangoPolicyStore, "resolve_policy", boom)
    with pytest.raises(CommandError, match="store down"):
        run("alice")
