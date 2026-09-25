from __future__ import annotations

from typing import Any

import pytest

from django_tolap import TolapDenied, ToolContext, tolap_context, tolap_tool
from django_tolap.contexts import issue_context
from django_tolap.store import DjangoPolicyStore
from django_tolap.tool import IDENTITY_MISSING
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db

SOURCE = "db:testapp:patients"


@pytest.fixture
def analyst(seeded: None) -> DjangoPolicyStore:
    store = DjangoPolicyStore()
    store.save_definition_json(
        {
            "version": "1.0",
            "name": "analyst",
            "permissions": {"canQuery": True},
            "objectRules": {
                "allowedObjects": ["patients"],
                "fieldRules": {"hiddenFields": ["ssn"]},
                "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
            },
        }
    )
    store.assign("analyst", user_id="alice", tenant_id="clinic", granted_by="a", reason="r")
    return store


@tolap_tool(source=SOURCE)
def patients_search(q: str, *, tolap: ToolContext) -> list[dict[str, Any]]:
    return tolap.enforce(Patient.objects.filter(full_name__icontains=q).order_by("id"))


def test_identity_from_kwargs(analyst: DjangoPolicyStore) -> None:
    rows = patients_search("o", user_id="alice", tenant_id="clinic")
    assert [r["id"] for r in rows] == [1, 3] and "ssn" not in rows[0]


def test_missing_identity_denied(analyst: DjangoPolicyStore) -> None:
    with pytest.raises(TolapDenied, match=IDENTITY_MISSING):
        patients_search("o")


def test_unknown_user_denied(analyst: DjangoPolicyStore) -> None:
    with pytest.raises(TolapDenied, match="query not permitted"):
        patients_search("o", user_id="mallory", tenant_id="clinic")


def test_identity_callable_derives_from_tool_arguments(analyst: DjangoPolicyStore) -> None:
    @tolap_tool(source=SOURCE, identity=lambda request, **_: (request["user"], request["tenant"]))
    def tool(request: dict[str, str], *, tolap: ToolContext) -> int:
        return len(tolap.enforce(Patient.objects.all()))

    assert tool(request={"user": "alice", "tenant": "clinic"}) == 2


def test_identity_from_settings(analyst: DjangoPolicyStore, settings) -> None:  # type: ignore[no-untyped-def]
    @tolap_tool(source=SOURCE)
    def tool(actor: str, *, tolap: ToolContext) -> int:
        return len(tolap.enforce(Patient.objects.all()))

    settings.TOLAP = {**settings.TOLAP, "IDENTITY": "tests.test_tool.identity_from_actor"}
    assert tool(actor="alice") == 2
    settings.TOLAP = {**settings.TOLAP, "IDENTITY": "tests.test_tool.no_identity"}
    with pytest.raises(TolapDenied, match=IDENTITY_MISSING):
        tool(actor="alice")


def identity_from_actor(actor: str, **_: Any) -> tuple[str, str]:
    return actor, "clinic"


def no_identity(**_: Any) -> None:
    return None


def test_kwargs_take_precedence_over_identity_callable(analyst: DjangoPolicyStore) -> None:
    @tolap_tool(source=SOURCE, identity=lambda **_: ("mallory", "clinic"))
    def tool(*, tolap: ToolContext) -> int:
        return len(tolap.enforce(Patient.objects.all()))

    assert tool(user_id="alice", tenant_id="clinic") == 2


def test_supplied_context_bypasses_store_but_is_verified(analyst: DjangoPolicyStore) -> None:
    ctx = issue_context("alice", "clinic", SOURCE)
    assert len(patients_search("o", context=ctx)) == 2
    assert len(patients_search("o", context=ctx, user_id="alice", tenant_id="clinic")) == 2
    ctx.signature = "tampered"
    with pytest.raises(TolapDenied, match="invalid signature"):
        patients_search("o", context=ctx)


def test_custom_param_name_and_policy_access(analyst: DjangoPolicyStore) -> None:
    @tolap_tool(source=SOURCE, param="ctx")
    def tool(*, ctx: ToolContext) -> str:
        assert ctx.source == SOURCE
        return ctx.policy.source_profiles[0]

    assert tool(user_id="alice", tenant_id="clinic") == "analyst"


def test_deny_helper(analyst: DjangoPolicyStore) -> None:
    @tolap_tool(source=SOURCE)
    def tool(*, tolap: ToolContext) -> None:
        tolap.deny("tool refuses")

    with pytest.raises(TolapDenied) as exc:
        tool(user_id="alice", tenant_id="clinic")
    assert exc.value.reason == "tool refuses"


def test_context_manager(analyst: DjangoPolicyStore) -> None:
    with tolap_context("alice", "clinic", SOURCE) as tool:
        assert len(tool.enforce(Patient.objects.all())) == 2
    with pytest.raises(TolapDenied, match=IDENTITY_MISSING):
        with tolap_context(None, "clinic", SOURCE):
            pass


def test_denials_carry_no_row_data(analyst: DjangoPolicyStore) -> None:
    @tolap_tool(source=SOURCE)
    def tool(*, tolap: ToolContext) -> Any:
        return tolap.enforce(Patient.objects.values("ssn"))

    with pytest.raises(TolapDenied) as exc:
        tool(user_id="alice", tenant_id="clinic")
    assert str(exc.value) == "Access denied: denied fields: patients.ssn"
