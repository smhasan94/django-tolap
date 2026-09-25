from __future__ import annotations

from sqlalchemy import func, select, text

from sqlalchemy_tolap.precheck import CANNOT_INSPECT, MASKED_ANNOTATION, UNKNOWN_FIELD, precheck
from tests.harness.fixtures import effective_policy
from tests.sqlalchemy.models import Encounter, Patient


def policy(**object_rules):  # type: ignore[no-untyped-def]
    return effective_policy({"permissions": {"canQuery": True}, "objectRules": object_rules})


def test_can_query_and_objects() -> None:
    assert (
        precheck(select(Patient), effective_policy({"permissions": {"canQuery": False}})).reason
        == "query not permitted"
    )
    assert (
        precheck(select(Patient), policy(hiddenObjects=["patients"])).reason == "object is hidden"
    )
    joined = select(Patient).join(Encounter)
    assert (
        precheck(joined, policy(allowedObjects=["patients"])).reason == "object not in allowed set"
    )
    assert precheck(joined, policy(allowedObjects=["patients", "encounters"])).allowed


def test_unknown_field_and_patterns() -> None:
    assert precheck(
        select(Patient), policy(fieldRules={"hiddenFields": ["patients.nope"]})
    ).reason == UNKNOWN_FIELD.format(name="patients.nope")
    assert precheck(
        select(Patient), policy(fieldRules={"hiddenFields": ["encounters.nope"]})
    ).allowed
    assert precheck(select(Patient), policy(fieldRules={"hiddenFields": ["x*"]})).allowed


def test_hidden_field_references() -> None:
    p = policy(fieldRules={"hiddenFields": ["ssn"]})
    assert precheck(select(Patient), p).allowed
    for stmt in (
        select(Patient.id, Patient.ssn),
        select(Patient).where(Patient.ssn == "1"),
        select(Patient).order_by(Patient.ssn),
        select(Patient.id, func.upper(Patient.ssn).label("u")),
    ):
        assert precheck(stmt, p).reason == "denied fields: patients.ssn"
    assert precheck(select(Patient.id, Patient.region), p).allowed


def test_allowed_fields_and_masked_annotation() -> None:
    p = policy(fieldRules={"allowedFields": ["id", "region"]})
    assert precheck(select(Patient.id, Patient.region), p).allowed
    assert precheck(select(Patient.id).order_by(Patient.email), p).reason.startswith(
        "denied fields:"
    )
    p = policy(fieldRules={"maskedFields": [{"field": "email", "maskType": "hash"}]})
    assert precheck(
        select(Patient.id, func.upper(Patient.email).label("e")), p
    ).reason == MASKED_ANNOTATION.format(name="e")


def test_uninspectable_reason() -> None:
    p = effective_policy({"permissions": {"canQuery": True}})
    assert precheck(select(Patient.id).where(text("1=1")), p).reason == CANNOT_INSPECT.format(
        why="TextClause is not supported"
    )
