from __future__ import annotations

import pytest
from django.db import connection
from django.db.models import Count

from django_tolap.pushdown import NO_FIELDS_VISIBLE, prepare_queryset
from tests.harness.fixtures import effective_policy
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db


def policy(object_rules=None, limits=None):  # type: ignore[no-untyped-def]
    bare = {"permissions": {"canQuery": True}}
    if object_rules is not None:
        bare["objectRules"] = object_rules
    if limits is not None:
        bare["limits"] = limits
    return effective_policy(bare)


def sql(prep) -> str:  # type: ignore[no-untyped-def]
    return str(prep.queryset.query)


def test_default_projection_drops_hidden_and_yields_dicts(seeded: None) -> None:
    prep = prepare_queryset(
        Patient.objects.all(), policy({"fieldRules": {"hiddenFields": ["ssn"]}})
    )
    assert prep.allowed
    assert "ssn" not in prep.visible_fields and "email" in prep.visible_fields
    assert '"patients"."ssn"' not in sql(prep)
    rows = list(prep.queryset)
    assert isinstance(rows[0], dict) and "ssn" not in rows[0]


def test_row_filter_pushed_and_limit_applied(seeded: None) -> None:
    p = policy(
        {"rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}]},
        limits={"maxResults": 1},
    )
    prep = prepare_queryset(Patient.objects.order_by("id"), p)
    assert prep.fully_pushed_down and prep.pushed_filters and not prep.unpushable_filters
    assert "WHERE" in sql(prep) and "LIMIT 1" in sql(prep)
    assert [r["id"] for r in prep.queryset] == [1]


def test_unpushable_filter_reported_and_not_in_sql(seeded: None) -> None:
    p = policy({"rowFilters": [{"field": "full_name", "operator": "startsWith", "value": "J"}]})
    prep = prepare_queryset(Patient.objects.all(), p)
    assert prep.allowed and not prep.fully_pushed_down
    assert [f.field for f in prep.unpushable_filters] == ["full_name"]
    assert "WHERE" not in sql(prep)


def test_filtered_field_kept_in_projection_even_when_hidden(seeded: None) -> None:
    p = policy(
        {
            "fieldRules": {"hiddenFields": ["region"]},
            "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
        }
    )
    prep = prepare_queryset(Patient.objects.values("id"), p)
    assert prep.allowed
    assert prep.projection == ("id", "region")
    assert "region" not in prep.visible_fields


def test_caller_projection_is_intersected_not_widened(seeded: None) -> None:
    prep = prepare_queryset(Patient.objects.values("id", "region"), policy())
    assert prep.projection == ("id", "region")
    assert set(next(iter(prep.queryset)).keys()) == {"id", "region"}


def test_caller_projection_naming_hidden_field_is_denied(seeded: None) -> None:
    p = policy({"fieldRules": {"hiddenFields": ["ssn"]}})
    prep = prepare_queryset(Patient.objects.values("id", "ssn"), p)
    assert not prep.allowed and prep.denial_reason.startswith("denied fields:")


def test_allowed_fields_projection(seeded: None) -> None:
    p = policy({"fieldRules": {"allowedFields": ["patients.id", "region"]}})
    prep = prepare_queryset(Patient.objects.values("id", "region"), p)
    assert prep.allowed and prep.projection == ("id", "region")


def test_empty_allowed_fields_denies(seeded: None) -> None:
    p = policy({"fieldRules": {"allowedFields": []}})
    prep = prepare_queryset(Patient.objects.values("id"), p)
    assert prep.denial_reason.startswith("denied fields:")
    # A pattern allow-list that matches nothing on this model: precheck passes for a
    # query referencing nothing visible? No -- every query references its projection.
    # The "no fields visible" reason is reachable only when the projection is empty
    # before the reference check, which values() never yields; guard the constant anyway.
    assert NO_FIELDS_VISIBLE == "no fields visible"


def test_annotations_kept_in_projection(seeded: None) -> None:
    qs = Patient.objects.annotate(n=Count("encounters"))
    prep = prepare_queryset(qs, policy({"fieldRules": {"hiddenFields": ["ssn"]}}))
    assert prep.projection[-1] == "n"
    assert all("n" in r and "ssn" not in r for r in prep.queryset)
    prep = prepare_queryset(qs.values("id", "n"), policy())
    assert prep.projection == ("id", "n")


def test_existing_narrower_slice_is_kept_and_wider_is_narrowed(seeded: None) -> None:
    p = policy(limits={"maxResults": 3})
    prep = prepare_queryset(Patient.objects.order_by("id")[:2], p)
    assert "LIMIT 2" in sql(prep)
    prep = prepare_queryset(Patient.objects.order_by("id")[:5], p)
    assert "LIMIT 3" in sql(prep)
    prep = prepare_queryset(Patient.objects.order_by("id")[1:5], p)
    assert "LIMIT 3 OFFSET 1" in sql(prep)
    assert [r["id"] for r in prep.queryset] == [2, 3, 4]


def test_sliced_queryset_pushes_no_row_filters(seeded: None) -> None:
    p = policy({"rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}]})
    prep = prepare_queryset(Patient.objects.order_by("id")[:3], p)
    assert prep.allowed and not prep.pushed_filters and len(prep.unpushable_filters) == 1
    assert "WHERE" not in sql(prep)


def test_no_limit_means_no_slice(seeded: None) -> None:
    prep = prepare_queryset(Patient.objects.all(), policy())
    assert "LIMIT" not in sql(prep) and prep.max_results is None


def test_denied_prep_carries_reason() -> None:
    prep = prepare_queryset(Patient.objects.extra(select={"x": "1"}), policy())
    assert not prep.allowed and prep.queryset is None
    assert prep.denial_reason is not None and "cannot be inspected" in prep.denial_reason


def test_manager_accepted(seeded: None) -> None:
    assert prepare_queryset(Patient.objects, policy()).allowed


def test_vendor_is_taken_from_connection(seeded: None) -> None:
    p = policy({"rowFilters": [{"field": "full_name", "operator": "like", "value": "J%"}]})
    prep = prepare_queryset(Patient.objects.all(), p)
    assert bool(prep.pushed_filters) == (connection.vendor == "postgresql")
