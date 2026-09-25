"""Upstream fixtures resolved through both stores must agree byte for byte."""

from __future__ import annotations

import json

import pytest
from tolap_core import deserialize_policy_assignment, deserialize_policy_definition, serialize
from tolap_store import InMemoryPolicyStore, StaticIdentityResolver

from django_tolap.store import DjangoPolicyStore
from tests.harness.fixtures import UPSTREAM

pytestmark = pytest.mark.django_db

MERGE_SCENARIOS = sorted((UPSTREAM / "merge-scenarios").glob("*.json"))
ASSIGNMENTS = sorted((UPSTREAM / "assignments").glob("*.json"))


def _both() -> tuple[DjangoPolicyStore, InMemoryPolicyStore]:
    resolver = StaticIdentityResolver(
        {"user-alice": ["research-analysts", "analysts"]}, {"user-alice": ["clinician"]}
    )
    return DjangoPolicyStore(identity_resolver=resolver), InMemoryPolicyStore(resolver)


def _same(ours, theirs) -> None:  # type: ignore[no-untyped-def]
    ours.resolved_at = theirs.resolved_at
    assert serialize(ours) == serialize(theirs)


@pytest.mark.parametrize("path", MERGE_SCENARIOS, ids=lambda p: p.stem)
def test_merge_scenario_parity(path) -> None:  # type: ignore[no-untyped-def]
    doc = json.loads(path.read_text())
    inputs = [d for d in doc["inputs"] if "purposeProfile" not in d]
    if len(inputs) != len(doc["inputs"]):
        pytest.skip("purpose profiles need tolap-core >= 1.1")
    ours, theirs = _both()
    for raw in inputs:
        definition = deserialize_policy_definition(raw)
        ours.save_definition(definition)
        theirs.save_definition(definition)
        assignment = deserialize_policy_assignment(
            {
                "version": "1.0",
                "policyName": definition.name,
                "assignee": {"type": "user", "identifier": "user-alice"},
                "scope": {},
                "active": True,
                "audit": {
                    "grantedBy": "t",
                    "grantedAt": "2026-01-01T00:00:00Z",
                    "reason": "fixture",
                },
            }
        )
        ours.save_assignment(assignment)
        theirs.save_assignment(assignment)
    mine = ours.resolve_policy("user-alice", "tenant", "db:x:y")
    _same(mine, theirs.resolve_policy("user-alice", "tenant", "db:x:y"))
    expected = doc["expected"]
    if "sourceProfiles" in expected:
        assert mine.source_profiles == expected["sourceProfiles"]
    assert mine.permissions.can_query == expected["permissions"]["canQuery"]


@pytest.mark.parametrize("path", ASSIGNMENTS, ids=lambda p: p.stem)
def test_assignment_fixture_parity(path) -> None:  # type: ignore[no-untyped-def]
    raw = json.loads(path.read_text())
    assignment = deserialize_policy_assignment(raw)
    definition = deserialize_policy_definition(
        {
            "version": "1.0",
            "name": assignment.policy_name,
            "permissions": {"canQuery": True},
            "limits": {"maxResults": 7},
        }
    )
    ours, theirs = _both()
    for store in (ours, theirs):
        store.save_definition(definition)
        store.save_assignment(assignment)
    tenant = assignment.scope.tenant_id or "tenant"
    source = assignment.scope.source_connection_id or "db:x:y"
    for user in (assignment.assignee.identifier, "user-alice", "stranger"):
        _same(
            ours.resolve_policy(user, tenant, source), theirs.resolve_policy(user, tenant, source)
        )
