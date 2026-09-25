"""``compile_filter`` per operator per vendor.

On the vendor under test the compiled ``Q`` is executed and its row set compared with
upstream's ``apply_row_filters`` on the same rows (the definition of a faithful push). For
every other vendor the decision (pushed or declined) is asserted without executing.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection
from tolap_core import FilterOperator, RowFilter, apply_row_filters

from django_tolap.pushdown import VENDORS, compile_filter
from tests.harness.fixtures import effective_policy
from tests.testapp.models import Encounter, Patient

pytestmark = pytest.mark.django_db

ROWS = [
    ("alice smith", "us-east", 10, "active"),
    ("ALICE JONES", "us-west", 50, "active"),
    ("bob stone", "eu-west", 90, "deleted"),
    ("Bob_Stone", None, None, "active"),
    ("m", "US-EAST", 3, "active"),
]


@pytest.fixture
def rows() -> None:
    for i, (name, region, score, status) in enumerate(ROWS, start=1):
        Patient.objects.create(
            id=i,
            full_name=name,
            email=f"{i}@x",
            ssn="s",
            date_of_birth=dt.date(2000, 1, i),
            region=region,
            status=status,
            score=score,
        )


def rf(field: str, operator: str, value=None, values=None) -> RowFilter:  # type: ignore[no-untyped-def]
    return RowFilter(field=field, operator=FilterOperator(operator), value=value, values=values)


def upstream_ids(row_filter: RowFilter) -> list[int]:
    rows = list(Patient.objects.values("id", "full_name", "region", "score", "status"))
    policy = effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "rowFilters": [
                    {
                        "field": row_filter.field,
                        "operator": row_filter.operator.value,
                        **({"value": row_filter.value} if row_filter.value is not None else {}),
                        **({"values": row_filter.values} if row_filter.values is not None else {}),
                    }
                ]
            },
        }
    )
    return sorted(r["id"] for r in apply_row_filters(rows, policy))


CASES = [
    rf("region", "equals", "us-east"),
    rf("region", "equals", None),
    rf("patients.region", "equals", "us-east"),
    rf("REGION", "equals", "us-east"),
    rf("region", "notEquals", "us-east"),
    rf("region", "notEquals", None),
    rf("score", "equals", 10),
    rf("score", "notEquals", 10),
    rf("region", "in", values=["us-east", "us-west"]),
    rf("region", "in", values=["us-east", None]),
    rf("region", "in", values=[]),
    rf("region", "notIn", values=["us-east"]),
    rf("region", "notIn", values=["us-east", None]),
    rf("region", "notIn", values=[]),
    rf("score", "greaterThan", 10),
    rf("score", "greaterThanOrEqual", 10),
    rf("score", "lessThan", 50),
    rf("score", "lessThanOrEqual", 50),
    rf("score", "greaterThan", None),
    rf("score", "between", values=[10, 50]),
    rf("score", "between", values=[50, 10]),
    rf("score", "between", values=[10]),
    rf("score", "between", values=[None, 50]),
    rf("region", "isNull"),
    rf("region", "isNotNull"),
    rf("full_name", "like", "alice%"),
    rf("full_name", "like", "%\\_%"),
    rf("full_name", "notLike", "alice%"),
    rf("full_name", "like", "b_b%"),
    rf("full_name", "greaterThan", "b"),
    rf("full_name", "between", values=["a", "c"]),
]


def _id(case: RowFilter) -> str:
    return f"{case.field}-{case.operator.value}-{case.value!r}-{case.values!r}"


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_pushed_filter_selects_exactly_upstream_rows(rows: None, case: RowFilter) -> None:
    q = compile_filter(case, Patient, connection.vendor)
    if q is None:
        pytest.skip(f"declined on {connection.vendor}")
    pushed = sorted(Patient.objects.filter(q).values_list("id", flat=True))
    assert pushed == upstream_ids(case)


@pytest.mark.parametrize(
    "case",
    [
        rf("full_name", "contains", "a"),
        rf("full_name", "startsWith", "a"),
        rf("full_name", "matches", "a.*"),
    ],
    ids=_id,
)
@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_never_pushed(case: RowFilter, vendor: str) -> None:
    assert compile_filter(case, Patient, vendor) is None


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_like_only_where_case_sensitive(vendor: str) -> None:
    pushed = compile_filter(rf("full_name", "like", "a%"), Patient, vendor) is not None
    assert pushed == VENDORS[vendor].like


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_string_equality_and_order_per_vendor(vendor: str) -> None:
    rules = VENDORS[vendor]
    eq = compile_filter(rf("region", "equals", "x"), Patient, vendor) is not None
    order = compile_filter(rf("region", "greaterThan", "x"), Patient, vendor) is not None
    between = compile_filter(rf("region", "between", values=["a", "b"]), Patient, vendor)
    assert eq == rules.string_equality
    assert order == rules.string_order
    assert (between is not None) == rules.string_order
    assert compile_filter(rf("score", "equals", 1), Patient, vendor) is not None


def test_unknown_vendor_declines_everything() -> None:
    assert compile_filter(rf("score", "equals", 1), Patient, "mssql") is None
    assert compile_filter(rf("region", "isNull"), Patient, "mssql") is None


@pytest.mark.parametrize(
    "case",
    [
        rf("score", "equals", "10"),
        rf("score", "equals", True),
        rf("region", "equals", 5),
        rf("score", "in", values=[1, "2"]),
        rf("score", "between", values=[1, "2"]),
        rf("full_name", "like", 5),
        rf("date_of_birth", "equals", "2000-01-01"),
        rf("date_of_birth", "greaterThan", "2000-01-01"),
        rf("encounters.status", "equals", "active"),
        rf("nope", "equals", 1),
        rf("full_name", "like", "a" * 1025),
    ],
    ids=_id,
)
def test_type_mismatch_other_object_and_unknown_field_decline(case: RowFilter) -> None:
    assert compile_filter(case, Patient, "postgresql") is None


def test_relation_field_declined() -> None:
    assert compile_filter(rf("patient", "equals", 1), Encounter, "postgresql") is None


def test_isnull_pushed_for_any_field_kind() -> None:
    assert compile_filter(rf("date_of_birth", "isNull"), Patient, "postgresql") is not None


@pytest.mark.parametrize("vendor", sorted(VENDORS))
@pytest.mark.parametrize("operator", ["equals", "in", "like", "greaterThan", "between"])
def test_nul_byte_values_are_never_pushed(vendor: str, operator: str) -> None:
    """PostgreSQL cannot bind a NUL byte as text; the post pass evaluates it instead."""
    value = "us\x00east"
    rf = {"field": "region", "operator": operator}
    if operator in ("in", "between"):
        rf["values"] = [value, "us-east"]
    else:
        rf["value"] = value
    policy = effective_policy(
        {"permissions": {"canQuery": True}, "objectRules": {"rowFilters": [rf]}}
    )
    assert compile_filter(policy.object_rules.row_filters[0], Patient, vendor) is None
