"""Decision 2026-09-25 item 4: how Django negation treats NULL before we add anything.

Django compiles ``~Q(f=x)`` on a nullable field to ``NOT (f = x AND f IS NOT NULL)``, which
keeps null rows -- upstream's rule for every negative operator. A plain ``f__in=[..., None]``
drops the ``None`` member, so ``in`` with a null member needs an explicit ``IS NULL`` arm.
These tests pin both facts on every vendor CI runs.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection
from django.db.models import Q
from tolap_core import apply_row_filters

from tests.harness.fixtures import effective_policy
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db


@pytest.fixture
def null_rows() -> None:
    for i, (region, score) in enumerate(
        [("us-east", 5), ("us-west", None), (None, 7), (None, None)], start=1
    ):
        Patient.objects.create(
            id=i,
            full_name="n",
            email="e",
            ssn="s",
            date_of_birth=dt.date(2000, 1, 1),
            region=region,
            status="a",
            score=score,
        )


def ids(qs) -> list[int]:  # type: ignore[no-untyped-def]
    return sorted(qs.values_list("id", flat=True))


def post_pass_ids(row_filter: dict) -> list[int]:  # type: ignore[type-arg]
    rows = list(Patient.objects.values("id", "region", "score"))
    policy = effective_policy(
        {"permissions": {"canQuery": True}, "objectRules": {"rowFilters": [row_filter]}}
    )
    return sorted(r["id"] for r in apply_row_filters(rows, policy))


def test_negated_lookup_sql_keeps_nulls_on_nullable_field() -> None:
    sql = str(Patient.objects.filter(~Q(region="x")).query)
    assert "IS NOT NULL" in sql and "NOT (" in sql
    sql = str(Patient.objects.filter(~Q(status="x")).query)
    assert "IS NOT NULL" not in sql  # NOT NULL column: no arm needed and none added


def test_not_equals_matches_upstream(null_rows: None) -> None:
    expected = post_pass_ids({"field": "region", "operator": "notEquals", "value": "us-east"})
    assert expected == [2, 3, 4]
    assert ids(Patient.objects.filter(~Q(region="us-east"))) == expected


def test_not_in_matches_upstream(null_rows: None) -> None:
    expected = post_pass_ids({"field": "region", "operator": "notIn", "values": ["us-east"]})
    assert expected == [2, 3, 4]
    assert ids(Patient.objects.filter(~Q(region__in=["us-east"]))) == expected


def test_in_with_null_member_needs_isnull_arm(null_rows: None) -> None:
    expected = post_pass_ids({"field": "region", "operator": "in", "values": ["us-east", None]})
    assert expected == [1, 3, 4]
    assert ids(Patient.objects.filter(region__in=["us-east", None])) == [1]
    assert ids(Patient.objects.filter(Q(region__in=["us-east"]) | Q(region__isnull=True))) == (
        expected
    )


def test_equals_null_is_is_null(null_rows: None) -> None:
    expected = post_pass_ids({"field": "region", "operator": "equals", "value": None})
    assert expected == [3, 4]
    assert ids(Patient.objects.filter(region__isnull=True)) == expected


def test_negated_comparison_keeps_nulls(null_rows: None) -> None:
    assert ids(Patient.objects.filter(~Q(score__gt=5))) == [1, 2, 4]
    assert connection.vendor  # documents the vendor this ran on in -v output
