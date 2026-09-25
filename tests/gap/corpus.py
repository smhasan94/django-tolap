"""Realistic QuerySets for measuring the gap between upstream's string rewriter and ORM pushdown.

Each entry is a name, a factory and a one-line description. The policies in ``POLICIES``
are typical: one hides a column, one only filters rows. ``str(qs.query)`` is handed to
upstream ``prepare_sql_query`` exactly as Django renders it; the ORM path uses
``prepare_queryset``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db.models import Avg, Count, Exists, F, OuterRef, Q, Subquery, TextField, Value
from django.db.models.functions import Concat, Upper

from tests.harness.fixtures import effective_policy
from tests.testapp.models import Encounter, Patient

Factory = Callable[[], Any]

CORPUS: list[tuple[str, Factory, str]] = [
    ("all", lambda: Patient.objects.all(), "default projection, no filter"),
    ("values_subset", lambda: Patient.objects.values("id", "region", "status"), "explicit columns"),
    (
        "filter_icontains",
        lambda: Patient.objects.filter(full_name__icontains="o"),
        "parameterised LIKE",
    ),
    (
        "filter_in_and_or",
        lambda: Patient.objects.filter(Q(region__in=["us-east", "us-west"]) | Q(status="deleted")),
        "combined Q",
    ),
    (
        "exclude_null",
        lambda: Patient.objects.exclude(region__isnull=True),
        "negated lookup on nullable",
    ),
    ("order_slice", lambda: Patient.objects.order_by("-date_of_birth")[:3], "ORDER BY + LIMIT"),
    ("offset_slice", lambda: Patient.objects.order_by("id")[2:5], "LIMIT with OFFSET"),
    ("only", lambda: Patient.objects.only("full_name", "region"), "only()"),
    ("defer", lambda: Patient.objects.defer("ssn", "email"), "defer()"),
    (
        "join_forward",
        lambda: Encounter.objects.filter(patient__region="us-east"),
        "forward FK join",
    ),
    (
        "join_reverse",
        lambda: Patient.objects.filter(encounters__status="active"),
        "reverse FK join",
    ),
    (
        "join_reverse_distinct",
        lambda: Patient.objects.filter(encounters__status="active").distinct(),
        "reverse join + DISTINCT",
    ),
    ("select_related", lambda: Encounter.objects.select_related("patient"), "select_related join"),
    (
        "annotate_count",
        lambda: Patient.objects.annotate(n=Count("encounters")),
        "aggregate annotation + GROUP BY",
    ),
    (
        "annotate_avg_having",
        lambda: Patient.objects.annotate(avg=Avg("encounters__id")).filter(avg__gt=0),
        "HAVING",
    ),
    (
        "annotate_func",
        lambda: Patient.objects.annotate(upper=Upper("full_name")),
        "function annotation",
    ),
    (
        "annotate_concat_value",
        lambda: Patient.objects.annotate(
            label=Concat(F("region"), Value("-"), F("status"), output_field=TextField())
        ),
        "expression with Value",
    ),
    (
        "exists_subquery",
        lambda: Patient.objects.filter(Exists(Encounter.objects.filter(patient=OuterRef("pk")))),
        "EXISTS subquery",
    ),
    (
        "subquery_annotation",
        lambda: Patient.objects.annotate(
            last=Subquery(
                Encounter.objects.filter(patient=OuterRef("pk"))
                .order_by("-occurred_at")
                .values("status")[:1]
            )
        ),
        "scalar subquery annotation",
    ),
    (
        "in_subquery",
        lambda: Patient.objects.filter(
            pk__in=Encounter.objects.filter(status="deleted").values("patient_id")
        ),
        "IN (subquery)",
    ),
    (
        "values_related",
        lambda: Encounter.objects.values("id", "patient__region"),
        "values() across a relation",
    ),
    (
        "values_annotate_group",
        lambda: Patient.objects.values("region").annotate(n=Count("id")),
        "GROUP BY via values().annotate()",
    ),
    ("f_comparison", lambda: Patient.objects.filter(score__gt=F("id")), "F() comparison"),
    (
        "dates_range",
        lambda: Patient.objects.filter(date_of_birth__range=("1970-01-01", "1989-12-31")),
        "BETWEEN on dates",
    ),
]

POLICIES: dict[str, Any] = {
    "hide-ssn-filter-region": effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "allowedObjects": ["patients", "encounters"],
                "fieldRules": {"hiddenFields": ["patients.ssn"]},
                "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
            },
            "limits": {"maxResults": 100},
        }
    ),
    "filter-only": effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "allowedObjects": ["patients", "encounters"],
                "rowFilters": [
                    {"field": "region", "operator": "in", "values": ["us-east", "us-west"]},
                    {"field": "status", "operator": "notEquals", "value": "deleted"},
                ],
            },
            "limits": {"maxResults": 100},
        }
    ),
}
