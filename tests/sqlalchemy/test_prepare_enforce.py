from __future__ import annotations

import datetime as dt
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from sqlalchemy_tolap import EnforcementMode, TolapDenied, enforce
from sqlalchemy_tolap.enforce import dialect_name
from sqlalchemy_tolap.pushdown import DIALECTS, NO_FIELDS_VISIBLE, prepare_select
from tests.harness.contexts import signed
from tests.harness.fixtures import effective_policy, us_east_filter
from tests.sqlalchemy.conftest import SIGNING_KEY
from tests.sqlalchemy.models import Encounter, Patient, audit_log, encounters, patients
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
    dialect = dialect_name(seeded)
    p = policy(
        {"rowFilters": [us_east_filter(DIALECTS[dialect].string_equality)]},
        limits={"maxResults": 1},
    )
    prep = prepare_select(select(Patient).order_by(Patient.id), p, dialect=dialect)
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


def test_aliased_root_pushes_onto_the_alias(seeded: Session) -> None:
    from sqlalchemy.orm import aliased

    dialect = dialect_name(seeded)
    p = policy(
        {
            "fieldRules": {"hiddenFields": ["ssn"]},
            "rowFilters": [us_east_filter(DIALECTS[dialect].string_equality)],
        },
        limits={"maxResults": 5},
    )
    a = aliased(Patient)
    prep = prepare_select(select(a).order_by(a.id), p, dialect=dialect)
    text = sql(prep)
    assert (
        text.count("FROM") == 1
        and "patients_1.region" in text
        and "patients.region" not in text.replace("patients_1", "")
    )
    rows = [dict(r) for r in seeded.execute(prep.statement).mappings()]
    assert [r["id"] for r in rows] == [1, 3] and "ssn" not in rows[0]


def test_connection_executor(seeded: Session) -> None:
    conn = seeded.connection()
    rows = enforce(
        select(patients.c.id).order_by(patients.c.id),
        signed(policy()),
        conn,
        signing_key=SIGNING_KEY,
    )
    assert len(rows) == 6


def test_joined_columns_masked_and_hidden_by_their_own_object(seeded: Session) -> None:
    """Mirror of the Django test: ``patients.email`` masks the joined column on an
    Encounter root, the caller's keys are preserved, a hidden joined column is refused."""
    p = policy(
        {
            "fieldRules": {
                "hiddenFields": ["patients.ssn"],
                "maskedFields": [{"field": "patients.email", "maskType": "hash"}],
            }
        }
    )
    stmt = (
        select(
            Encounter.id,
            Encounter.status,
            Patient.email.label("patient_email"),
            Patient.region.label("patient_region"),
        )
        .join(Patient)
        .order_by(Encounter.id)
    )
    rows = enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY)
    assert set(rows[0]) == {"id", "status", "patient_email", "patient_region"}
    assert rows[0]["patient_email"] == hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]
    assert rows[0]["patient_region"] == "us-east"
    denied = prepare_select(
        select(Encounter.id, Patient.ssn.label("s")).join(Patient), p, dialect="sqlite"
    )
    assert not denied.allowed and "patients.ssn" in (denied.denial_reason or "")
    # A labelled root column is that column: masked under the caller's key.
    rows = enforce(
        select(Patient.id, Patient.email.label("mail")).order_by(Patient.id),
        signed(p),
        seeded,
        signing_key=SIGNING_KEY,
    )
    assert rows[0] == {"id": 1, "mail": hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]}


def test_bare_joined_column_with_root_filter_and_limit(seeded: Session) -> None:
    dialect = dialect_name(seeded)
    p = policy(
        {"rowFilters": [us_east_filter(DIALECTS[dialect].string_equality)]},
        limits={"maxResults": 2},
    )
    stmt = select(Patient.id, Encounter.occurred_at).join(Encounter).order_by(Patient.id)
    prep = prepare_select(stmt, p, dialect=dialect)
    assert prep.allowed and prep.projection[:2] == ("id", "occurred_at")
    assert prep.key_map["occurred_at"] == "encounters.occurred_at"
    rows = enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY)
    assert rows and all(set(r) == {"id", "occurred_at"} for r in rows) and len(rows) <= 2
    plain = seeded.execute(stmt.where(Patient.region == "us-east").limit(2)).mappings().all()
    assert [dict(r) for r in plain] == rows


def test_allowed_fields_on_root_only_denies_joined_column(seeded: Session) -> None:
    p = policy({"fieldRules": {"allowedFields": ["encounters.id", "encounters.status"]}})
    with pytest.raises(TolapDenied):
        enforce(
            select(Encounter.id, Patient.region.label("r")).join(Patient),
            signed(p),
            seeded,
            signing_key=SIGNING_KEY,
        )


def test_qualified_root_filter_is_not_intercepted_by_a_renamed_key(seeded: Session) -> None:
    """``patients.region`` must be read from the patient, never from a joined
    ``encounters.region`` presented under a qualified key (upstream falls back to a
    bare-name match over the row's keys when the exact key is absent)."""
    when = dt.datetime(2026, 1, 1)
    seeded.execute(
        insert(encounters),
        [
            # Explicit ids: the seed sets ids too, so the sequence is behind on PostgreSQL.
            {"id": 901, "patient_id": 1, "occurred_at": when, "region": "us-west", "status": "x"},
            {"id": 902, "patient_id": 5, "occurred_at": when, "region": "us-east", "status": "x"},
        ],
    )
    p = policy(
        {"rowFilters": [{"field": "patients.region", "operator": "equals", "value": "us-east"}]}
    )
    stmt = (
        select(Encounter.region.label("er"), Patient.id)
        .select_from(Patient)
        .join(Encounter)
        .order_by(Encounter.id)
    )
    results = [
        enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY, mode=mode)
        for mode in EnforcementMode
    ]
    for rows in results:
        assert rows and {r["id"] for r in rows} <= {1, 3}
        assert all(set(r) == {"er", "id"} for r in rows)
    assert results[0] == results[1]

    # A filter on the joined table, however spelled, reads the joined column.
    joined = policy(
        {"rowFilters": [{"field": "Encounters.Region", "operator": "equals", "value": "us-east"}]}
    )
    results = [
        enforce(stmt, signed(joined), seeded, signing_key=SIGNING_KEY, mode=mode)
        for mode in EnforcementMode
    ]
    assert results[0] == results[1]
    assert all(r["er"] == "us-east" for r in results[0]) and 5 in {r["id"] for r in results[0]}
    assert 1 in {r["id"] for r in results[0]}  # patient 1 keeps its seeded us-east encounter

    # A filter on a joined table whose column is not in the result cannot be evaluated.
    from sqlalchemy_tolap.pushdown import FILTER_NOT_IN_RESULT

    bare = select(Patient.id, Encounter.occurred_at).join(Encounter)
    prep = prepare_select(bare, joined, dialect=dialect_name(seeded))
    assert not prep.allowed
    assert prep.denial_reason == FILTER_NOT_IN_RESULT.format(field="Encounters.Region")
    # A filter on a table outside the query cannot be evaluated either.
    outside = prepare_select(select(Patient.id), joined, dialect=dialect_name(seeded))
    assert outside.denial_reason == FILTER_NOT_IN_RESULT.format(field="Encounters.Region")


def test_filter_on_a_labelled_root_column_beside_a_joined_namesake(seeded: Session) -> None:
    """The label's key is renamed for the post pass, so the filter's spelling is copied."""
    p = policy({"rowFilters": [{"field": "REGION", "operator": "equals", "value": "us-east"}]})
    stmt = (
        select(Encounter.region.label("er"), Patient.id, Patient.region.label("REGION"))
        .select_from(Patient)
        .join(Encounter)
        .order_by(Encounter.id)
    )
    results = [
        enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY, mode=mode)
        for mode in EnforcementMode
    ]
    assert results[0] == results[1] and results[0]
    assert all(r["REGION"] == "us-east" and set(r) == {"er", "id", "REGION"} for r in results[0])


def test_callers_own_key_for_a_filtered_column_is_kept(seeded: Session) -> None:
    p = policy({"rowFilters": [{"field": "REGION", "operator": "equals", "value": "us-east"}]})
    stmt = select(Patient.id, Patient.region.label("REGION")).order_by(Patient.id)
    rows = enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY)
    assert rows == [{"id": 1, "REGION": "us-east"}, {"id": 3, "REGION": "us-east"}]


def test_aliased_root_with_explicit_columns(seeded: Session) -> None:
    from sqlalchemy.orm import aliased

    a = aliased(Patient)
    p = policy(
        {"rowFilters": [{"field": "patients.region", "operator": "equals", "value": "us-east"}]}
    )
    stmt = select(a.id, a.region.label("where")).select_from(a).order_by(a.id)
    results = [
        enforce(stmt, signed(p), seeded, signing_key=SIGNING_KEY, mode=mode)
        for mode in EnforcementMode
    ]
    assert (
        results[0] == results[1] == [{"id": 1, "where": "us-east"}, {"id": 3, "where": "us-east"}]
    )
