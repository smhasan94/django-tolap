"""``enforce_sql`` / ``enforce_raw``: the raw SQL paths get the QuerySet path's guarantees."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from django_tolap import TolapDenied, enforce, enforce_raw, enforce_sql
from django_tolap.pushdown import VENDORS, EnforcementMode
from django_tolap.raw import RawPreparation, escape_outside_placeholders, prepare_sql
from tests.harness.contexts import signed
from tests.harness.differential import canonical
from tests.harness.fixtures import effective_policy, us_east_filter
from tests.harness.strategies import patient_rows, policies
from tests.test_enforce import ANALYST
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db


def policy(object_rules=None, limits=None):  # type: ignore[no-untyped-def]
    bare = {"permissions": {"canQuery": True}}
    if object_rules is not None:
        bare["objectRules"] = object_rules
    if limits is not None:
        bare["limits"] = limits
    return effective_policy(bare)


def prep(sql: str, p: Any, params: Any = None, **kw: Any) -> RawPreparation:
    return prepare_sql(sql, params, p, model=Patient, vendor=connection.vendor, **kw)


# --- README policy, both entry points ------------------------------------------------------


def test_raw_matches_queryset_path(seeded: None) -> None:
    ctx = signed(effective_policy(ANALYST))
    via_orm = enforce(Patient.objects.order_by("id"), ctx)
    via_raw = enforce_raw(Patient.objects.raw("SELECT * FROM patients ORDER BY id"), ctx)
    via_sql = enforce_sql("SELECT * FROM patients ORDER BY id", None, ctx, model=Patient)
    assert via_raw == via_orm == via_sql
    assert [r["id"] for r in via_raw] == [1, 2, 3] and "ssn" not in via_raw[0]
    assert all(type(r) is dict for r in via_raw)


def test_placeholders_list_and_dict(seeded: None) -> None:
    ctx = signed(
        policy({"rowFilters": [us_east_filter(VENDORS[connection.vendor].string_equality)]})
    )
    by_list = enforce_sql(
        "SELECT id, region FROM patients WHERE status = %s ORDER BY id",
        ["active"],
        ctx,
        model=Patient,
    )
    by_dict = enforce_sql(
        "SELECT id, region FROM patients WHERE status = %(s)s ORDER BY id",
        {"s": "active"},
        ctx,
        model=Patient,
    )
    assert [r["id"] for r in by_list] == [1, 3] == [r["id"] for r in by_dict]


def test_pushed_filter_and_limit_land_in_sql(seeded: None) -> None:
    p = policy(
        {"rowFilters": [us_east_filter(VENDORS[connection.vendor].string_equality)]},
        limits={"maxResults": 1},
    )
    r = prep("SELECT id, region FROM patients ORDER BY id", p, ["x"])
    assert r.allowed and r.rewritten and r.fully_pushed_down and r.max_results == 1
    assert r.sql is not None and "WHERE" in r.sql and "LIMIT 1" in r.sql
    rows = enforce_sql(
        "SELECT id, region FROM patients ORDER BY id", None, signed(p), model=Patient
    )
    assert [row["id"] for row in rows] == [1]


def test_limit_pushed_only_when_every_filter_pushed(seeded: None) -> None:
    p = policy(
        {"rowFilters": [{"field": "full_name", "operator": "startsWith", "value": "J"}]},
        limits={"maxResults": 1},
    )
    r = prep("SELECT id, full_name FROM patients", p)
    assert r.allowed and not r.fully_pushed_down and r.max_results is None
    assert r.sql is not None and "LIMIT" not in r.sql
    assert [x.operator.value for x in r.unpushable_filters] == ["startsWith"]


def test_post_only_mode_pushes_nothing_and_agrees(seeded: None) -> None:
    p = policy(
        {"rowFilters": [{"field": "id", "operator": "in", "values": [1, 3]}]},
        limits={"maxResults": 5},
    )
    r = prep("SELECT id FROM patients ORDER BY id", p, mode="postOnly")
    assert r.allowed and not r.rewritten and not r.pushed_filters and r.max_results is None
    sql = "SELECT id FROM patients ORDER BY id"
    assert enforce_sql(sql, None, signed(p), model=Patient, mode="postOnly") == enforce_sql(
        sql, None, signed(p), model=Patient
    )


# --- what is never rewritten but still allowed --------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT p.id FROM patients p JOIN encounters e ON e.patient_id = p.id",
        "SELECT patients.id FROM patients, encounters",
        "SELECT id FROM patients WHERE id IN (SELECT patient_id FROM encounters)",
        "SELECT id FROM patients UNION SELECT id FROM patients",
    ],
)
def test_multi_table_statements_are_checked_but_not_rewritten(seeded: None, sql: str) -> None:
    p = policy(
        {"rowFilters": [{"field": "id", "operator": "in", "values": [1]}]}, limits={"maxResults": 1}
    )
    r = prep(sql, p)
    assert r.allowed and not r.rewritten and not r.pushed_filters and r.max_results is None
    assert len(r.unpushable_filters) == 1
    rows = enforce_sql(sql, None, signed(p), model=Patient)
    assert [row["id"] for row in rows] == [1]  # the post pass still filters and limits


def test_unknown_vendor_pushes_nothing() -> None:
    p = policy({"rowFilters": [{"field": "id", "operator": "equals", "value": 1}]})
    r = prepare_sql("SELECT id FROM patients", None, p, model=Patient, vendor="oracle")
    assert r.allowed and not r.rewritten and not r.pushed_filters


# --- denials ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("INSERT INTO patients (id) VALUES (9)", "only SELECT"),
        ("DELETE FROM patients", "only SELECT"),
        ("SELECT id FROM encounters", "not 'patients'"),
        ("", "only SELECT"),
    ],
)
def test_denied_statements(sql: str, reason: str) -> None:
    r = prep(sql, policy())
    assert not r.allowed and r.denial_reason and reason in r.denial_reason
    with pytest.raises(TolapDenied):
        enforce_sql(sql, None, signed(policy()), model=Patient)


def test_denied_by_upstream_checks(seeded: None) -> None:
    hidden = policy({"fieldRules": {"hiddenFields": ["patients.ssn"]}})
    assert not prep("SELECT id, ssn FROM patients", hidden).allowed
    not_allowed = policy({"allowedObjects": ["encounters"]})
    assert not prep("SELECT id FROM patients", not_allowed).allowed
    with pytest.raises(TolapDenied):
        enforce_sql("SELECT id, ssn FROM patients", None, signed(hidden), model=Patient)


def test_bad_signature_refused_before_anything(seeded: None) -> None:
    ctx = signed(policy())
    with pytest.raises(TolapDenied, match="signature"):
        enforce_sql("SELECT id FROM patients", None, ctx, model=Patient, signing_key="other")


# --- placeholder escaping -----------------------------------------------------------------


def test_escape_outside_placeholders() -> None:
    assert (
        escape_outside_placeholders(
            "SELECT a FROM t WHERE (b LIKE 'J%') AND (c = %s) AND d = %(n)s"
        )
        == "SELECT a FROM t WHERE (b LIKE 'J%%') AND (c = %s) AND d = %(n)s"
    )
    assert escape_outside_placeholders("no percent") == "no percent"


def test_pushed_like_survives_parameter_interpolation(seeded: None) -> None:
    p = policy({"rowFilters": [{"field": "full_name", "operator": "like", "value": "J%"}]})
    r = prep("SELECT id, full_name FROM patients WHERE status = %s ORDER BY id", p, ["active"])
    assert r.allowed
    if VENDORS[connection.vendor].like:
        assert r.pushed_filters and r.sql is not None and "'J%%'" in r.sql
    rows = enforce_sql(
        "SELECT id, full_name FROM patients WHERE status = %s ORDER BY id",
        ["active"],
        signed(p),
        model=Patient,
    )
    assert [row["id"] for row in rows] == [1, 2]  # John Smith, Jane Doe


def test_literal_that_looks_like_a_placeholder_falls_back() -> None:
    p = policy({"rowFilters": [{"field": "full_name", "operator": "like", "value": "%s%"}]})
    r = prepare_sql(
        "SELECT id FROM patients WHERE status = %s", ["a"], p, model=Patient, vendor="postgresql"
    )
    assert r.allowed and not r.pushed_filters and r.sql is not None and r.sql.count("%s") == 1


# --- differential -------------------------------------------------------------------------

RAW_STATEMENTS = [
    "SELECT * FROM patients",
    "SELECT id, region, status, score FROM patients ORDER BY id DESC",
    "SELECT * FROM patients WHERE status = %s OR score >= 50",
    "SELECT id, full_name FROM patients ORDER BY full_name",
    "SELECT * FROM patients WHERE region <> 'eu-west' ORDER BY id LIMIT 3",
    "SELECT p.id, p.region FROM patients p WHERE p.status = %s ORDER BY p.id",
]


class RawDifferentialProperty(TestCase):
    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        rows=patient_rows(),
        policy=policies(),
        which=st.integers(min_value=0, max_value=len(RAW_STATEMENTS) - 1),
    )
    def test_pushdown_matches_post_pass(
        self, rows: list[dict[str, Any]], policy: Any, which: int
    ) -> None:
        Patient.objects.all().delete()
        Patient.objects.bulk_create([Patient(**r) for r in rows])
        sql = RAW_STATEMENTS[which]
        params = ["active"] if "%s" in sql else None
        left = prepare_sql(sql, params, policy, model=Patient, vendor=connection.vendor)
        if not left.allowed:
            assert left.denial_reason
            return
        pushed = enforce_sql(sql, params, signed(policy), model=Patient)
        post = enforce_sql(
            sql, params, signed(policy), model=Patient, mode=EnforcementMode.post_only
        )
        if (
            left.max_results is not None
            and "ORDER BY" not in sql.upper()
            or "ORDER BY full_name" in sql
        ):
            assert len(pushed) == len(post)
            return
        assert canonical(pushed) == canonical(post), left.sql
