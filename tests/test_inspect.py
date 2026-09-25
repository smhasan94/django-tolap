from __future__ import annotations

import pytest
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Upper

from django_tolap.exceptions import Uninspectable
from django_tolap.inspect import FieldRef, inspect
from tests.testapp.models import Encounter, Patient

pytestmark = pytest.mark.django_db


def refs(qs) -> set[tuple[str, str]]:  # type: ignore[no-untyped-def]
    return {r.key for r in inspect(qs).referenced}


def test_plain_all_does_not_reference_default_columns() -> None:
    ins = inspect(Patient.objects.all())
    assert ins.root is Patient
    assert ins.models == frozenset({Patient})
    assert ins.referenced == frozenset()  # SELECT * is not an explicit reference
    assert ins.projected is None


def test_values_and_only_are_explicit_references_but_defer_is_not() -> None:
    assert FieldRef(Patient, "ssn") in inspect(Patient.objects.values("ssn")).referenced
    assert FieldRef(Patient, "ssn") in inspect(Patient.objects.only("ssn")).referenced
    assert FieldRef(Patient, "ssn") not in inspect(Patient.objects.defer("email")).referenced


def test_manager_accepted() -> None:
    assert inspect(Patient.objects).root is Patient


def test_filter_and_exclude_and_q() -> None:
    qs = Patient.objects.filter(Q(region="us-east") | Q(status="active")).exclude(score__gt=3)
    keys = refs(qs)
    assert {("testapp.patient", "region"), ("testapp.patient", "status")} <= keys
    assert ("testapp.patient", "score") in keys


def test_order_by_string_and_expression_and_meta_ordering() -> None:
    assert ("testapp.patient", "email") in refs(Patient.objects.order_by("-email"))
    assert ("testapp.patient", "email") in refs(Patient.objects.order_by(Upper("email")))


def test_joined_filter_adds_related_model_and_field() -> None:
    ins = inspect(Patient.objects.filter(encounters__status="active"))
    assert ins.models == frozenset({Patient, Encounter})
    assert FieldRef(Encounter, "status") in ins.referenced


def test_forward_join_from_encounter() -> None:
    ins = inspect(Encounter.objects.filter(patient__region="us-east"))
    assert ins.models == frozenset({Patient, Encounter})
    assert FieldRef(Patient, "region") in ins.referenced


def test_values_projection_and_annotation_sources() -> None:
    qs = Patient.objects.values("id", "region").annotate(n=Count("encounters"))
    ins = inspect(qs)
    assert ins.projected == ("id", "region", "n")
    assert ins.annotations["n"] == frozenset({FieldRef(Encounter, "id")})
    assert Encounter in ins.models


def test_annotation_upper_email_sources() -> None:
    ins = inspect(Patient.objects.annotate(e=Upper("email")))
    assert ins.annotations["e"] == frozenset({FieldRef(Patient, "email")})


def test_values_pk_alias() -> None:
    assert inspect(Patient.objects.values("pk")).projected == ("id",)


def test_values_empty_means_all() -> None:
    assert inspect(Patient.objects.values()).projected is None


def test_only_and_defer() -> None:
    assert inspect(Patient.objects.only("email")).projected == ("id", "email")
    deferred = inspect(Patient.objects.defer("ssn")).projected
    assert deferred is not None and "ssn" not in deferred and "email" in deferred


def test_subquery_and_exists() -> None:
    latest = Encounter.objects.filter(patient=OuterRef("pk")).order_by("-occurred_at")
    qs = Patient.objects.annotate(last=Subquery(latest.values("status")[:1])).filter(
        Exists(Encounter.objects.filter(patient=OuterRef("pk"), region="eu-west"))
    )
    ins = inspect(qs)
    assert Encounter in ins.models
    assert FieldRef(Encounter, "region") in ins.referenced
    assert FieldRef(Encounter, "status") in ins.referenced


def test_in_subquery_rhs() -> None:
    inner = Encounter.objects.filter(status="deleted").values("patient_id")
    ins = inspect(Patient.objects.filter(pk__in=inner))
    assert Encounter in ins.models
    assert FieldRef(Encounter, "status") in ins.referenced


def test_f_expression_and_value() -> None:
    keys = refs(Patient.objects.filter(score__gt=F("id") + Value(1)))
    assert ("testapp.patient", "id") in keys and ("testapp.patient", "score") in keys


def test_slice_marks() -> None:
    ins = inspect(Patient.objects.all()[5:15])
    assert (ins.low_mark, ins.high_mark) == (5, 15)


@pytest.mark.parametrize(
    "qs_factory",
    [
        lambda: Patient.objects.extra(where=["1=1"]),
        lambda: Patient.objects.annotate(x=RawSQL("1", ())),
        lambda: Patient.objects.filter(region="a").union(Patient.objects.filter(region="b")),
        lambda: Patient.objects.raw("SELECT * FROM patients"),
        lambda: Patient.objects.values("encounters__status"),
        lambda: Patient.objects.only("encounters__status"),
        lambda: Patient.objects.select_for_update(),
    ],
    ids=["extra", "rawsql", "union", "raw", "joined-values", "joined-only", "for-update"],
)
def test_refused_constructs(qs_factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Uninspectable):
        inspect(qs_factory())


def test_select_related_touches_model_but_projects_root_only() -> None:
    ins = inspect(Encounter.objects.select_related("patient"))
    assert Patient in ins.models
    assert ins.projected is None
