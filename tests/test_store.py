from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from tolap_core import deserialize_policy_assignment, serialize
from tolap_store import InMemoryPolicyStore, StaticIdentityResolver

from django_tolap.identity import DjangoGroupsIdentityResolver, load_identity_resolver
from django_tolap.models import PolicyAssignment, PolicyDefinition
from django_tolap.store import DjangoPolicyStore
from tests.harness.fixtures import UPSTREAM

pytestmark = pytest.mark.django_db


def definition(name: str, **extra):  # type: ignore[no-untyped-def]
    return {"version": "1.0", "name": name, "permissions": {"canQuery": True}, **extra}


@pytest.fixture
def store() -> DjangoPolicyStore:
    return DjangoPolicyStore(
        identity_resolver=StaticIdentityResolver({"alice": ["analysts"]}, {"alice": ["clinician"]})
    )


def test_definition_crud(store: DjangoPolicyStore) -> None:
    store.save_definition_json(definition("p", description="one"))
    assert store.get_definition("p") is not None and store.get_definition("p").description == "one"  # type: ignore[union-attr]
    store.save_definition_json(definition("p", description="two"))
    assert [d.description for d in store.list_definitions()] == ["two"]
    assert PolicyDefinition.objects.count() == 1
    assert store.delete_definition("p") is True
    assert store.delete_definition("p") is False
    assert store.get_definition("p") is None


def test_inactive_definition_not_listed(store: DjangoPolicyStore) -> None:
    store.save_definition_json(definition("p"), active=False)
    assert store.get_definition("p") is None and store.list_definitions() == []


def test_save_definition_upstream_object(store: DjangoPolicyStore) -> None:
    from tolap_core import deserialize_policy_definition

    upstream = deserialize_policy_definition(
        json.loads((UPSTREAM / "policies" / "healthcare-analyst.json").read_text())
    )
    store.save_definition(upstream)
    assert serialize(store.get_definition(upstream.name)) == serialize(upstream)


def test_assignments_filtered_in_sql(store: DjangoPolicyStore) -> None:
    now = timezone.now()
    for name in (
        "direct",
        "grp",
        "role",
        "svc",
        "inactive",
        "expired",
        "revoked",
        "other-tenant",
        "other-user",
    ):
        store.save_definition_json(definition(name))
    store.assign("direct", user_id="alice", granted_by="a", reason="r")
    store.assign("grp", group="analysts", tenant_id="t1", granted_by="a", reason="r")
    store.assign("role", role="clinician", granted_by="a", reason="r")
    store.assign("svc", service_account="alice", granted_by="a", reason="r")
    store.assign("inactive", user_id="alice", granted_by="a", reason="r")
    PolicyAssignment.objects.filter(policy_id="inactive").update(active=False)
    store.assign(
        "expired", user_id="alice", granted_by="a", reason="r", expires_at=now - timedelta(days=1)
    )
    store.assign("revoked", user_id="alice", granted_by="a", reason="r")
    PolicyAssignment.objects.filter(policy_id="revoked").update(revoked_at=now - timedelta(hours=1))
    store.assign("other-tenant", user_id="alice", tenant_id="t2", granted_by="a", reason="r")
    store.assign("other-user", user_id="bob", granted_by="a", reason="r")
    names = sorted(a.policy_name for a in store.get_assignments("alice", "t1"))
    assert names == ["direct", "grp", "role", "svc"]
    assert sorted(a.policy_name for a in store.get_assignments("bob", "t1")) == ["other-user"]


def test_future_revocation_still_in_force(store: DjangoPolicyStore) -> None:
    store.save_definition_json(definition("p"))
    store.assign("p", user_id="alice", granted_by="a", reason="r")
    PolicyAssignment.objects.update(revoked_at=timezone.now() + timedelta(days=1))
    assert [a.policy_name for a in store.get_assignments("alice", "t")] == ["p"]
    assert store.resolve_policy("alice", "t", "db:x:y").source_profiles == ["p"]


def test_save_assignment_replaces_on_policy_and_identifier(store: DjangoPolicyStore) -> None:
    store.save_definition_json(definition("p"))
    raw = json.loads((UPSTREAM / "assignments" / "user-direct.json").read_text())
    raw["policyName"] = "p"
    store.save_assignment(deserialize_policy_assignment(raw))
    raw["scope"] = {"tenantId": "changed"}
    store.save_assignment(deserialize_policy_assignment(raw))
    rows = list(PolicyAssignment.objects.all())
    assert len(rows) == 1 and rows[0].tenant_id == "changed"
    assert store.delete_assignment("p", raw["assignee"]["identifier"]) is True
    assert store.delete_assignment("p", raw["assignee"]["identifier"]) is False


def test_assign_requires_exactly_one_assignee(store: DjangoPolicyStore) -> None:
    store.save_definition_json(definition("p"))
    with pytest.raises(ValueError):
        store.assign("p", granted_by="a", reason="r")
    with pytest.raises(ValueError):
        store.assign("p", user_id="u", group="g", granted_by="a", reason="r")


def test_resolve_matches_in_memory_store(store: DjangoPolicyStore) -> None:
    resolver = StaticIdentityResolver({"alice": ["analysts"]}, {"alice": ["clinician"]})
    memory = InMemoryPolicyStore(resolver)
    defs = [
        definition(
            "base",
            priority=10,
            objectRules={"fieldRules": {"hiddenFields": ["dob"]}},
            limits={"maxResults": 100},
        ),
        definition(
            "team",
            priority=20,
            objectRules={
                "allowedObjects": ["patients", "encounters"],
                "fieldRules": {"hiddenFields": ["ssn"]},
            },
            limits={"maxResults": 1000},
        ),
        definition(
            "extra",
            priority=30,
            objectRules={"allowedObjects": ["patients"], "fieldRules": {"hiddenFields": ["mrn"]}},
            limits={"maxResults": 500},
        ),
    ]
    for d in defs:
        store.save_definition_json(d)
        from tolap_core import deserialize_policy_definition

        memory.save_definition(deserialize_policy_definition(d))
    store.assign("base", role="clinician", granted_by="a", reason="r")
    store.assign("team", group="analysts", tenant_id="t", granted_by="a", reason="r")
    store.assign("extra", user_id="alice", granted_by="a", reason="r")
    for a in store.get_assignments("alice", "t"):
        memory.save_assignment(a)
    ours = store.resolve_policy("alice", "t", "db:analytics:patients")
    theirs = memory.resolve_policy("alice", "t", "db:analytics:patients")
    ours.resolved_at = theirs.resolved_at
    assert serialize(ours) == serialize(theirs)
    assert ours.limits is not None and ours.limits.max_results == 100
    assert sorted(ours.object_rules.field_rules.hidden_fields) == ["dob", "mrn", "ssn"]  # type: ignore[union-attr]
    assert ours.object_rules.allowed_objects == ["patients"]  # type: ignore[union-attr]


def test_declared_purpose_refused_on_core_1_0(store: DjangoPolicyStore) -> None:
    with pytest.raises(NotImplementedError):
        store.resolve_policy("alice", "t", "db:x:y", declared_purpose="campaign-x")


def test_django_groups_identity_resolver() -> None:
    user = get_user_model().objects.create_user(username="alice", password="x")
    user.groups.add(Group.objects.create(name="analysts"))
    resolver = DjangoGroupsIdentityResolver()
    assert resolver.get_groups(str(user.pk)) == ["analysts"]
    assert resolver.get_groups("alice") == ["analysts"]
    assert resolver.get_groups("nobody") == [] and resolver.get_groups("999") == []
    assert resolver.get_roles("alice") == []


def test_load_identity_resolver_from_settings(settings) -> None:  # type: ignore[no-untyped-def]
    assert isinstance(load_identity_resolver(), DjangoGroupsIdentityResolver)
    settings.TOLAP = {"SIGNING_KEY": "k", "IDENTITY_RESOLVER": "tests.test_store.CustomResolver"}
    assert isinstance(load_identity_resolver(), CustomResolver)


class CustomResolver:
    def get_groups(self, user_id: str) -> list[str]:
        return ["g"]

    def get_roles(self, user_id: str) -> list[str]:
        return ["r"]
