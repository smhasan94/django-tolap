from __future__ import annotations

import json

import pytest
from django.db.models import Count
from django.db.models.functions import Upper

from django_tolap.precheck import (
    CANNOT_INSPECT,
    MASKED_ANNOTATION,
    UNKNOWN_FIELD,
    precheck,
)
from tests.harness.fixtures import UPSTREAM, effective_policy
from tests.testapp.models import Encounter, Patient

pytestmark = pytest.mark.django_db


def policy(**object_rules):  # type: ignore[no-untyped-def]
    return effective_policy({"permissions": {"canQuery": True}, "objectRules": object_rules})


def test_can_query_false() -> None:
    p = effective_policy({"permissions": {"canQuery": False}})
    assert precheck(Patient.objects.all(), p).reason == "query not permitted"


def test_no_object_rules_is_permissive() -> None:
    p = effective_policy({"permissions": {"canQuery": True}})
    assert precheck(Patient.objects.all(), p).allowed


def test_root_object_hidden_and_not_allowed() -> None:
    assert precheck(Patient.objects.all(), policy(hiddenObjects=["patients"])).reason == (
        "object is hidden"
    )
    assert precheck(Patient.objects.all(), policy(allowedObjects=["encounters"])).reason == (
        "object not in allowed set"
    )


def test_joined_object_must_be_allowed() -> None:
    qs = Patient.objects.filter(encounters__status="active")
    assert precheck(qs, policy(allowedObjects=["patients"])).reason == "object not in allowed set"
    assert precheck(qs, policy(allowedObjects=["patients", "encounters"])).allowed
    assert precheck(qs, policy(hiddenObjects=["encounters"])).reason == "object is hidden"


def test_unknown_field_denies() -> None:
    p = policy(fieldRules={"hiddenFields": ["patients.nope"]})
    assert precheck(Patient.objects.all(), p).reason == UNKNOWN_FIELD.format(name="patients.nope")
    p = policy(rowFilters=[{"field": "missing", "operator": "equals", "value": 1}])
    assert precheck(Patient.objects.all(), p).reason == UNKNOWN_FIELD.format(name="missing")


def test_unknown_field_qualified_with_other_object_is_skipped() -> None:
    p = policy(fieldRules={"hiddenFields": ["encounters.nope"]})
    assert precheck(Patient.objects.all(), p).allowed


def test_pattern_fields_are_exempt_from_unknown_check() -> None:
    assert precheck(Patient.objects.all(), policy(fieldRules={"hiddenFields": ["x*"]})).allowed


def test_hidden_field_referenced_anywhere_denies() -> None:
    p = policy(fieldRules={"hiddenFields": ["ssn"]})
    assert precheck(Patient.objects.all(), p).allowed  # SELECT *: hidden column projected out
    for qs in (
        Patient.objects.only("ssn"),
        Patient.objects.filter(ssn="1"),
        Patient.objects.order_by("ssn"),
        Patient.objects.values("id", "ssn"),
        Patient.objects.annotate(u=Upper("ssn")).values("id", "u"),
    ):
        assert precheck(qs, p).reason.startswith("denied fields:")
    assert precheck(Patient.objects.values("id", "region"), p).allowed


def test_qualified_and_bare_forms_both_match() -> None:
    assert precheck(
        Patient.objects.values("ssn"), policy(fieldRules={"hiddenFields": ["patients.ssn"]})
    ).reason.startswith("denied fields:")
    assert precheck(
        Patient.objects.values("id"), policy(fieldRules={"allowedFields": ["patients.id"]})
    ).allowed
    assert precheck(
        Patient.objects.values("id"), policy(fieldRules={"allowedFields": ["id"]})
    ).allowed


def test_allowed_fields_restricts_references() -> None:
    p = policy(fieldRules={"allowedFields": ["id", "region"]})
    assert precheck(Patient.objects.values("id", "region"), p).allowed
    assert precheck(Patient.objects.values("id", "region").order_by("email"), p).reason.startswith(
        "denied fields:"
    )
    assert precheck(Patient.objects.all(), p).allowed


def test_empty_allowed_fields_denies_every_reference() -> None:
    assert precheck(
        Patient.objects.values("id"), policy(fieldRules={"allowedFields": []})
    ).reason.startswith("denied fields:")


def test_hidden_joined_field() -> None:
    p = policy(fieldRules={"hiddenFields": ["encounters.status"]})
    assert precheck(Patient.objects.filter(encounters__status="x"), p).reason.startswith(
        "denied fields:"
    )
    # Upstream's post-pass matcher drops the qualifier on both sides (connector spec
    # section 3.2), so "encounters.status" also strips a bare "status" key from patient
    # rows. The pre-check agrees with the boundary rather than being looser than it.
    assert precheck(Patient.objects.filter(status="x"), p).reason.startswith("denied fields:")
    assert precheck(Patient.objects.filter(region="x").values("id", "region"), p).allowed


def test_masked_field_in_annotation_denies() -> None:
    p = policy(fieldRules={"maskedFields": [{"field": "email", "maskType": "hash"}]})
    assert precheck(Patient.objects.annotate(e=Upper("email")), p).reason == (
        MASKED_ANNOTATION.format(name="e")
    )
    assert precheck(Patient.objects.annotate(n=Count("encounters")), p).allowed


def test_uninspectable_reason() -> None:
    p = effective_policy({"permissions": {"canQuery": True}})
    result = precheck(Patient.objects.extra(select={"x": "1"}), p)
    assert result.reason == CANNOT_INSPECT.format(why="extra() is not supported")
    result = precheck(Patient.objects.extra(where=["1=1"]), p)
    assert result.reason == CANNOT_INSPECT.format(why="raw SQL fragments are not supported")


def test_precedence_can_query_before_object() -> None:
    p = effective_policy(
        {"permissions": {"canQuery": False}, "objectRules": {"hiddenObjects": ["patients"]}}
    )
    assert precheck(Patient.objects.all(), p).reason == "query not permitted"


@pytest.mark.parametrize(
    "case",
    json.loads((UPSTREAM / "enforcement" / "validate-object-access.json").read_text())["cases"]
    + json.loads(
        (UPSTREAM / "enforcement" / "validate-object-access-glob-metacharacters.json").read_text()
    )["cases"],
    ids=lambda c: f"{c['objectName']}",
)
def test_object_access_fixture_via_encounter_model(case, settings) -> None:  # type: ignore[no-untyped-def]
    """Route upstream's object-access cases through OBJECT_NAME so the name under test is used."""
    settings.TOLAP = {"SIGNING_KEY": "k", "OBJECT_NAME": "tests.test_precheck.fixture_object_name"}
    fixture_object_name.name = case["objectName"]
    p = effective_policy(case["policy"])
    result = precheck(Encounter.objects.all(), p)
    assert result.allowed == case["expected"]["allowed"]
    if "reason" in case["expected"]:
        assert result.reason == case["expected"]["reason"]


def fixture_object_name(model):  # type: ignore[no-untyped-def]
    return fixture_object_name.name  # type: ignore[attr-defined]


fixture_object_name.name = "patients"  # type: ignore[attr-defined]
