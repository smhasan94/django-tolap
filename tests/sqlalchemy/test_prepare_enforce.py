from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sqlalchemy_tolap import EnforcementMode, TolapDenied, enforce
from sqlalchemy_tolap.enforce import dialect_name
from sqlalchemy_tolap.pushdown import NO_FIELDS_VISIBLE, prepare_select
from tests.harness.contexts import signed
from tests.harness.fixtures import effective_policy
from tests.sqlalchemy.conftest import SIGNING_KEY
from tests.sqlalchemy.models import Encounter, Patient, audit_log, patients
from tests.test_enforce import ANALYST


def policy(object_rules=None, limits=None):  # type: ignore[no-untyped-def]
    bare = {"permissions": {"canQuery": True}}
    if object_rules is not None:
        bare["objectRules"] = object_rules
    if limits is not None:
        bare["limits"] = limits
    return effective_policy(bare)


def sql(prep) -> str:  # type: ignore[no-untyped-def]
    return str(prep.statement)


def test_default_projection_drops_hidden(seeded: Session) -> None:
    prep = prepare_select(
        select(Patient),
        policy({"fieldRules": {"hiddenFields": ["ssn"]}}),
        dialect=dialect_name(seeded),
    )
    assert prep.allowed and "ssn" not in prep.visible_fields and "ssn" not in sql(prep)
    rows = [dict(r) for r in seeded.execute(prep.statement).mappings()]
    assert "ssn" not in rows[0] and "email" in rows[0]


def test_row_filter_pushed_and_limit(seeded: Session) -> None:
    p = policy(
        {"rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}]},
        limits={"maxResults": 1},
    )
    prep = prepare_select(select(Patient).order_by(Patient.id), p, dialect=dialect_name(seeded))
    assert prep.fully_pushed_down and "WHERE" in sql(prep) and "LIMIT" in sql(prep)
    assert [r["id"] for r in seeded.execute(prep.statement).mappings()] == [1]


def test_unpushable_reported_and_limit_not_pushed(seeded: Session) -> None:
    p = policy(
        {"rowFilters": [{"field": "full_name", "operator": "startsWith", "value": "J"}]},
        limits={"maxResults": 1},
    )
    prep = prepare_select(select(Patient), p, dialect=dialect_name(seeded))
    assert prep.allowed and not prep.fully_pushed_down and "WHERE" not in sql(prep)
    assert "LIMIT" not in sql(prep)


def test_filter_field_kept_and_stripped(seeded: Session) -> None:
    p = policy(
        {
            "fieldRules": {"hiddenFields": ["region"]},
            "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
        }
    )
    prep = prepare_select(select(Patient.id), p, dialect=dialect_name(seeded))
    assert prep.projection == ("id", "region") and prep.extra_fields == ("region",)
    rows = enforce(
        select(Patient.id).order_by(Patient.id), signed(p), seeded, signing_key=SIGNING_KEY
    )
    assert rows == [{"id": 1}, {"id": 3}]


def test_caller_projection_hidden_denied_and_empty_allowed(seeded: Session) -> None:
    p = policy({"fieldRules": {"hiddenFields": ["ssn"]}})
    assert (
        prepare_select(select(Patient.id, Patient.ssn), p, dialect="sqlite").denial_reason
        == "denied fields: patients.ssn"
    )
    assert prepare_select(
        select(Patient.id), policy({"fieldRules": {"allowedFields": []}}), dialect="sqlite"
    ).denial_reason.startswith("denied fields:")
    assert NO_FIELDS_VISIBLE == "no fields visible"


def test_existing_limit_narrowed_and_sliced_pushes_no_filters(seeded: Session) -> None:
    dialect = dialect_name(seeded)
    filtered = policy(
        {"rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}]},
        limits={"maxResults": 3},
    )
    prep = prepare_select(select(Patient).order_by(Patient.id).limit(5), filtered, dialect=dialect)
    # Sliced by the caller: no filter is pushed, so the limit is left as written too.
    assert prep.statement._limit == 5 and not prep.pushed_filters
    assert len(prep.unpushable_filters) == 1
    unfiltered = policy(limits={"maxResults": 3})
    prep = prepare_select(
        select(Patient).order_by(Patient.id).limit(5), unfiltered, dialect=dialect
    )
    assert prep.statement._limit == 3
    prep = prepare_select(
        select(Patient).order_by(Patient.id).limit(2), unfiltered, dialect=dialect
    )
    assert prep.statement._limit == 2


def test_labels_kept(seeded: Session) -> None:
    stmt = (
        select(Patient.id, func.count(Encounter.id).label("n"))
        .join(Encounter)
        .group_by(Patient.id)
        .order_by(Patient.id)
    )
    rows = enforce(stmt, signed(policy()), seeded, signing_key=SIGNING_KEY)
    assert rows[0] == {"id": 1, "n": 1}


def test_readme_policy_end_to_end(seeded: Session) -> None:
    rows = enforce(
        select(Patient).order_by(Patient.id),
        signed(effective_policy(ANALYST)),
        seeded,
        signing_key=SIGNING_KEY,
    )
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert "ssn" not in rows[0] and rows[0]["full_name"] == "J" + "*" * 9
    assert rows[0]["email"] == hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]


def test_modes_agree_and_bad_mode_rejected(seeded: Session) -> None:
    ctx = signed(effective_policy(ANALYST))
    assert enforce(
        select(Patient).order_by(Patient.id), ctx, seeded, signing_key=SIGNING_KEY
    ) == enforce(
        select(Patient).order_by(Patient.id),
        ctx,
        seeded,
        signing_key=SIGNING_KEY,
        mode=EnforcementMode.post_only,
    )
    with pytest.raises(ValueError):
        enforce(select(Patient), ctx, seeded, signing_key=SIGNING_KEY, mode="rewriteOnly")


def test_denials(seeded: Session) -> None:
    ctx = signed(effective_policy(ANALYST))
    with pytest.raises(TolapDenied, match="object not in allowed set"):
        enforce(select(audit_log), ctx, seeded, signing_key=SIGNING_KEY)
    with pytest.raises(TolapDenied, match="invalid signature"):
        enforce(select(Patient), ctx, seeded, signing_key="wrong")
    with pytest.raises(TolapDenied, match="expired"):
        enforce(
            select(Patient),
            signed(effective_policy(ANALYST), ttl=timedelta(seconds=-1)),
            seeded,
            signing_key=SIGNING_KEY,
        )
    with pytest.raises(TolapDenied) as exc:
        enforce(select(Patient.id, Patient.ssn), ctx, seeded, signing_key=SIGNING_KEY)
    assert str(exc.value) == "Access denied: denied fields: patients.ssn"


def test_connection_executor(seeded: Session) -> None:
    conn = seeded.connection()
    rows = enforce(
        select(patients.c.id).order_by(patients.c.id),
        signed(policy()),
        conn,
        signing_key=SIGNING_KEY,
    )
    assert len(rows) == 6
