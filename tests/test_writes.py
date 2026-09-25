"""ORM write paths: ``enforce_save``, ``enforce_delete``, ``enforce_update``,
``enforce_queryset_delete``, and the ``ToolContext`` shortcuts."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from django_tolap import (
    TolapDenied,
    ToolContext,
    enforce_delete,
    enforce_queryset_delete,
    enforce_save,
    enforce_update,
)
from tests.harness.contexts import signed
from tests.harness.fixtures import effective_policy
from tests.testapp.models import Encounter, Patient

pytestmark = pytest.mark.django_db


def ctx(permissions: dict[str, Any] | None = None, **object_rules: Any) -> Any:
    perms = {"canQuery": True, "readOnly": True, **(permissions or {})}
    rules = {
        "allowedObjects": ["patients", "encounters"],
        "fieldRules": {"hiddenFields": ["patients.ssn"]},
        "rowFilters": [{"field": "id", "operator": "in", "values": [1, 2, 3]}],
        **object_rules,
    }
    return signed(effective_policy({"permissions": perms, "objectRules": rules}))


WRITER = {"readOnly": False, "canInsert": True, "canUpdate": True, "canDelete": True}


def new_patient(**overrides: Any) -> Patient:
    fields = {
        "full_name": "New Person",
        "email": "new@example.com",
        "ssn": "",
        "date_of_birth": dt.date(2000, 1, 1),
        "region": "us-east",
        "status": "active",
    }
    return Patient(**{**fields, **overrides})


# --- read-only ceiling ---------------------------------------------------------------------


def test_read_only_policy_refuses_every_write(seeded: None) -> None:
    c = ctx()
    with pytest.raises(TolapDenied, match="insert not permitted"):
        enforce_save(new_patient(), c)
    p = Patient.objects.get(pk=1)
    p.status = "x"
    with pytest.raises(TolapDenied):
        enforce_save(p, c)
    with pytest.raises(TolapDenied):
        enforce_delete(p, c)
    with pytest.raises(TolapDenied):
        enforce_update(Patient.objects.filter(pk=1), c, status="x")
    with pytest.raises(TolapDenied):
        enforce_queryset_delete(Patient.objects.filter(pk=1), c)
    assert Patient.objects.count() == 6 and Patient.objects.get(pk=1).status == "active"


# --- insert ---------------------------------------------------------------------------------


def test_insert_allowed_and_hidden_field_refused(seeded: None) -> None:
    c = ctx(WRITER)
    enforce_save(new_patient(), c)
    assert Patient.objects.count() == 7
    with pytest.raises(TolapDenied, match="ssn"):
        enforce_save(new_patient(ssn="111-22-3333"), c)
    assert Patient.objects.count() == 7


def test_insert_needs_can_insert(seeded: None) -> None:
    with pytest.raises(TolapDenied):
        enforce_save(new_patient(), ctx({**WRITER, "canInsert": False}))


# --- update ---------------------------------------------------------------------------------


def test_update_visible_row(seeded: None) -> None:
    c = ctx(WRITER)
    p = Patient.objects.get(pk=1)
    p.status = "inactive"
    enforce_save(p, c, update_fields=["status"])
    assert Patient.objects.get(pk=1).status == "inactive"


def test_update_invisible_row_refused(seeded: None) -> None:
    c = ctx(WRITER)
    p = Patient.objects.get(pk=5)  # outside the id-in-[1,2,3] filter
    p.status = "inactive"
    with pytest.raises(TolapDenied, match="target row not permitted"):
        enforce_save(p, c, update_fields=["status"])
    assert Patient.objects.get(pk=5).status == "active"


def test_full_save_is_a_full_replace_for_read_only_fields(seeded: None) -> None:
    c = ctx(WRITER, fieldRules={"hiddenFields": [], "readOnlyFields": ["patients.region"]})
    p = Patient.objects.get(pk=1)
    p.status = "inactive"
    with pytest.raises(TolapDenied, match="region"):
        enforce_save(p, c)  # overwrites every column, region included
    enforce_save(p, c, update_fields=["status"])  # names only what it changes
    assert Patient.objects.get(pk=1).status == "inactive"


def test_fk_update_field_uses_column_name(seeded: None) -> None:
    c = ctx(WRITER, fieldRules={"hiddenFields": [], "readOnlyFields": ["encounters.patient_id"]})
    e = Encounter.objects.get(pk=1)
    e.patient_id = 2
    with pytest.raises(TolapDenied, match="patient_id"):
        enforce_save(e, c, update_fields=["patient"])


# --- delete ---------------------------------------------------------------------------------


def test_delete_visible_and_invisible(seeded: None) -> None:
    c = ctx(WRITER)
    enforce_delete(Patient.objects.get(pk=2), c)
    assert not Patient.objects.filter(pk=2).exists()
    with pytest.raises(TolapDenied, match="target row not permitted"):
        enforce_delete(Patient.objects.get(pk=5), c)
    assert Patient.objects.filter(pk=5).exists()


def test_delete_needs_can_delete(seeded: None) -> None:
    with pytest.raises(TolapDenied):
        enforce_delete(Patient.objects.get(pk=1), ctx({**WRITER, "canDelete": False}))


# --- bulk -----------------------------------------------------------------------------------


def test_bulk_update_all_or_nothing(seeded: None) -> None:
    c = ctx(WRITER)
    assert enforce_update(Patient.objects.filter(pk__in=[1, 2]), c, status="x") == 2
    with pytest.raises(TolapDenied, match="target row not permitted"):
        enforce_update(Patient.objects.filter(pk__in=[3, 5]), c, status="y")
    assert Patient.objects.get(pk=3).status == "active"
    with pytest.raises(TolapDenied, match="ssn"):
        enforce_update(Patient.objects.filter(pk=1), c, ssn="1")


def test_bulk_delete_all_or_nothing(seeded: None) -> None:
    c = ctx(WRITER)
    with pytest.raises(TolapDenied, match="target row not permitted"):
        enforce_queryset_delete(Patient.objects.all(), c)
    assert Patient.objects.count() == 6
    assert enforce_queryset_delete(Patient.objects.filter(pk__in=[2, 3]), c) >= 2
    assert Patient.objects.count() == 4


# --- context and ToolContext ----------------------------------------------------------------


def test_bad_signature_refused_before_any_write(seeded: None) -> None:
    with pytest.raises(TolapDenied, match="signature"):
        enforce_save(new_patient(), ctx(WRITER), signing_key="other")
    assert Patient.objects.count() == 6


def test_tool_context_shortcuts(seeded: None) -> None:
    tool = ToolContext(context=ctx(WRITER), source="db:testapp:patients")
    p = new_patient()
    tool.save(p)
    assert Patient.objects.count() == 7
    assert tool.update(Patient.objects.filter(pk=1), status="z") == 1
    tool.delete(Patient.objects.get(pk=1))
    assert tool.delete_queryset(Patient.objects.filter(pk=2)) >= 1
    assert Patient.objects.count() == 5
