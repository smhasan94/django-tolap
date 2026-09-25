"""Property: for generated policies and rows, pushdown never changes the post pass's result."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Exists, OuterRef, Q
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from django_tolap.pushdown import prepare_queryset
from tests.harness.differential import assert_differential, post_only
from tests.harness.strategies import patient_rows, policies
from tests.testapp.models import Encounter, Patient

QUERYSETS = [
    lambda: Patient.objects.all(),
    lambda: Patient.objects.order_by("-id"),
    lambda: Patient.objects.values("id", "region", "status", "score"),
    lambda: Patient.objects.filter(Q(status="active") | Q(score__gte=50)),
    lambda: Patient.objects.exclude(region="eu-west").order_by("id"),
    lambda: Patient.objects.order_by("id")[1:4],
    lambda: Patient.objects.values("id", "full_name").order_by("full_name"),
    lambda: Patient.objects.only("region", "score").order_by("id"),
    lambda: Patient.objects.filter(encounters__status="active").distinct().order_by("id"),
    lambda: Patient.objects.annotate(n=Count("encounters")).filter(n__gte=0).order_by("id"),
    lambda: Patient.objects.filter(
        Exists(Encounter.objects.filter(patient=OuterRef("pk"), region="us-east"))
    ),
    lambda: Patient.objects.values("id", "region").annotate(n=Count("encounters")),
    lambda: Patient.objects.values("id", "region", "encounters__status").order_by("id"),
    lambda: Encounter.objects.values("id", "status", "patient__region", "patient__email").order_by(
        "id"
    ),
]


class DifferentialProperty(TestCase):
    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        rows=patient_rows(),
        policy=policies(),
        which=st.integers(min_value=0, max_value=len(QUERYSETS) - 1),
    )
    def test_pushdown_matches_post_pass(
        self, rows: list[dict[str, Any]], policy: Any, which: int
    ) -> None:
        Patient.objects.all().delete()
        Patient.objects.bulk_create([Patient(**r) for r in rows])
        Encounter.objects.bulk_create(
            [
                Encounter(
                    patient_id=r["id"],
                    occurred_at="2026-01-01T00:00:00Z",
                    # Never the patient's own region, so a filter evaluated against the
                    # wrong object's column changes the result.
                    region="us-west" if r["region"] == "us-east" else "us-east",
                    status=r["status"],
                )
                for r in rows
                if r["id"] % 2
            ]
        )
        qs = QUERYSETS[which]()
        prep = prepare_queryset(qs, policy)
        if not prep.allowed:
            # A denial is a denial on both paths: the post-only path runs the same pre-check.
            assert prep.denial_reason
            return
        assert_differential(qs, policy)

    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(rows=patient_rows(), policy=policies())
    def test_pushed_rows_are_a_subset_of_unfiltered_rows(
        self, rows: list[dict[str, Any]], policy: Any
    ) -> None:
        Patient.objects.all().delete()
        Patient.objects.bulk_create([Patient(**r) for r in rows])
        prep = prepare_queryset(Patient.objects.all(), policy)
        if not prep.allowed:
            return
        assert prep.queryset is not None
        fetched = list(prep.queryset)
        assert len(fetched) <= Patient.objects.count()
        assert len(fetched) >= len(post_only(Patient.objects.all(), policy))
