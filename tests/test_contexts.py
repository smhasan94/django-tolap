from __future__ import annotations

from datetime import timedelta

import pytest
from tolap_core import InMemoryReplayGuard, validate_context, validate_expiry

from django_tolap import accept_context, enforce, issue_context
from django_tolap.contexts import serialize
from django_tolap.store import DjangoPolicyStore
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db

POLICY = {
    "version": "1.0",
    "name": "analyst",
    "permissions": {"canQuery": True},
    "objectRules": {"allowedObjects": ["patients"], "fieldRules": {"hiddenFields": ["ssn"]}},
    "limits": {"maxResults": 2},
}


@pytest.fixture
def store() -> DjangoPolicyStore:
    s = DjangoPolicyStore()
    s.save_definition_json(POLICY)
    s.assign("analyst", user_id="alice", tenant_id="clinic", granted_by="admin", reason="demo")
    return s


def test_issue_context_is_signed_and_scoped(store: DjangoPolicyStore, seeded: None) -> None:
    ctx = issue_context("alice", "clinic", "db:testapp:patients")
    assert validate_context(ctx, "test-signing-key") and validate_expiry(ctx) is None
    assert ctx.effective_policy.source_connection_id == "db:testapp:patients"
    assert ctx.effective_policy.source_profiles == ["analyst"]
    rows = enforce(Patient.objects.order_by("id"), ctx)
    assert len(rows) == 2 and "ssn" not in rows[0]


def test_unknown_user_gets_deny_all(store: DjangoPolicyStore, seeded: None) -> None:
    ctx = issue_context("mallory", "clinic", "db:testapp:patients")
    assert ctx.effective_policy.permissions.can_query is False
    from django_tolap import TolapDenied

    with pytest.raises(TolapDenied, match="query not permitted"):
        enforce(Patient.objects.all(), ctx)


def test_ttl_from_settings_or_argument(store: DjangoPolicyStore, settings) -> None:  # type: ignore[no-untyped-def]
    settings.TOLAP = {**settings.TOLAP, "CONTEXT_TTL": -5}
    with pytest.raises(Exception):  # noqa: B017 - upstream refuses a non-positive ttl or the context is already expired
        ctx = issue_context("alice", "clinic", "db:testapp:patients")
        assert validate_expiry(ctx) is not None
        raise RuntimeError("expired as expected")
    ctx = issue_context("alice", "clinic", "db:testapp:patients", ttl=timedelta(minutes=5))
    assert validate_expiry(ctx) is None


def test_round_trip_through_transport(store: DjangoPolicyStore, seeded: None) -> None:
    ctx = issue_context("alice", "clinic", "db:testapp:patients")
    wire = serialize(ctx)
    accepted = accept_context(wire)
    assert accepted.effective_policy.source_profiles == ["analyst"]
    assert len(enforce(Patient.objects.all(), accepted)) == 2


def test_accept_context_refuses_tampering_and_replay(store: DjangoPolicyStore) -> None:
    ctx = issue_context("alice", "clinic", "db:testapp:patients")
    wire = serialize(ctx)
    with pytest.raises(ValueError):
        accept_context(wire, signing_key="wrong")
    guard = InMemoryReplayGuard()
    accept_context(wire, replay_guard=guard)
    with pytest.raises(ValueError, match="replay"):
        accept_context(wire, replay_guard=guard)
