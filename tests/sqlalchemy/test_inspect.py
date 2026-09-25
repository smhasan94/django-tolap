from __future__ import annotations

import pytest
from sqlalchemy import column, exists, func, literal_column, select, text
from sqlalchemy.orm import aliased

from sqlalchemy_tolap.exceptions import Uninspectable
from sqlalchemy_tolap.inspect import ColRef, inspect
from tests.sqlalchemy.models import Encounter, Patient, encounters, patients

_other = aliased(Patient)
_e1, _e2 = aliased(Encounter), aliased(Encounter)


def test_entity_select_is_default_projection() -> None:
    ins = inspect(select(Patient))
    assert ins.root is patients and ins.projected is None and ins.referenced == frozenset()
    assert set(ins.tables) == {"patients"}


def test_core_table_select_same() -> None:
    ins = inspect(select(patients).where(patients.c.region == "x"))
    assert ins.projected is None and ins.referenced == {ColRef("patients", "region")}


def test_explicit_columns_are_referenced() -> None:
    ins = inspect(select(Patient.id, Patient.ssn).order_by(Patient.email))
    assert ins.projected == ("id", "ssn")
    assert {
        ColRef("patients", "ssn"),
        ColRef("patients", "email"),
        ColRef("patients", "id"),
    } <= ins.referenced


def test_join_adds_table_onclause_and_where_columns() -> None:
    ins = inspect(select(Patient).join(Encounter).where(Encounter.status == "active"))
    assert set(ins.tables) == {"patients", "encounters"}
    assert ColRef("encounters", "status") in ins.referenced
    assert ColRef("encounters", "patient_id") in ins.referenced  # ON clause


def test_label_annotation_sources() -> None:
    ins = inspect(select(Patient.id, func.upper(Patient.email).label("e")))
    assert ins.annotations["e"] == frozenset({ColRef("patients", "email")})
    assert ins.projected == ("id", "e")


def test_group_by_having_and_subqueries() -> None:
    stmt = (
        select(Patient.id, func.count(Encounter.id).label("n"))
        .join(Encounter)
        .group_by(Patient.id)
        .having(func.count(Encounter.id) > 0)
    )
    ins = inspect(stmt)
    assert ColRef("encounters", "id") in ins.referenced
    sub = (
        select(Encounter.status)
        .where(Encounter.patient_id == Patient.id)
        .order_by(Encounter.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    ins = inspect(
        select(Patient.id, sub.label("last")).where(
            exists().where(Encounter.patient_id == Patient.id, Encounter.region == "eu-west")
        )
    )
    assert (
        ColRef("encounters", "region") in ins.referenced
        and ColRef("encounters", "status") in ins.referenced
    )
    assert "encounters" in ins.tables


def test_limit_offset() -> None:
    ins = inspect(select(Patient).limit(5).offset(2))
    assert (ins.limit, ins.offset) == (5, 2)


@pytest.mark.parametrize(
    "stmt_factory",
    [
        lambda: select(Patient.id).where(text("1=1")),
        lambda: select(literal_column("42").label("x"), Patient.id),
        lambda: select(Patient.id).where(column("region") == "x"),
        lambda: select(Patient.id).union(select(Patient.id)),
        lambda: select(patients.c.id).select_from(select(patients).subquery()),
        lambda: select(select(patients).cte().c.id),
        lambda: select(Patient, Encounter),
        lambda: select(Patient, Encounter.status),
        lambda: select(Patient.status, Encounter.status).join(Encounter),
        lambda: select(Patient.id, Encounter.region).join(Encounter),
        lambda: select(Patient.id, Encounter.status.label("region")).join(Encounter),
        lambda: select(Patient.id, Encounter.status.label("REGION")).join(Encounter),
        lambda: select(Patient.id, func.upper(Patient.full_name).label("encounters.status")),
        lambda: select(Patient.region, Patient.region.label("r")),
        lambda: select(Patient.id, _other.region.label("other")).join(
            _other, _other.id == Patient.id
        ),
        lambda: (
            select(Patient.id, _e1.region.label("r1"), _e2.status.label("s2"))
            .join(_e1, _e1.patient_id == Patient.id)
            .join(_e2, _e2.patient_id == Patient.id)
        ),
        lambda: (
            select(_other.id, patients.c.region.label("other_region"))
            .select_from(_other)
            .join(patients, patients.c.id == _other.id)
        ),
        lambda: select(func.count(Patient.id)),
    ],
    ids=[
        "text",
        "literal_column",
        "unattached",
        "union",
        "subquery-from",
        "cte",
        "two-entities",
        "mixed",
        "duplicate-key",
        "joined-shadows-root",
        "label-shadows-root",
        "label-shadows-root-case",
        "dotted-key",
        "column-twice",
        "alias-of-root",
        "table-twice",
        "root-alias-plus-table",
        "unlabelled",
    ],
)
def test_refused(stmt_factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Uninspectable):
        inspect(stmt_factory())


def test_aliased_table() -> None:
    from sqlalchemy.orm import aliased

    p = aliased(Patient)
    ins = inspect(select(p.id, p.region).where(p.status == "a"))
    assert ins.root is patients and ColRef("patients", "status") in ins.referenced
    assert ins.columns == {"id": ColRef("patients", "id"), "region": ColRef("patients", "region")}
    # A correlated subquery naming the root table again is not a second FROM copy.
    inner = select(Encounter.id).where(Encounter.patient_id == Patient.id).exists()
    assert inspect(select(Patient.id).where(inner)).root is patients
    assert encounters is not None


def test_joined_and_labelled_columns_are_keyed_to_their_object() -> None:
    """A non-root column, bare or labelled, and a labelled root column are plain columns
    under the caller's key; the post pass sees them as ``table.column``."""
    stmt = select(Patient.id, Encounter.occurred_at, Patient.email.label("mail")).join(Encounter)
    ins = inspect(stmt)
    assert ins.projected == ("id", "occurred_at", "mail")
    assert ins.renamed == {
        "occurred_at": ColRef("encounters", "occurred_at"),
        "mail": ColRef("patients", "email"),
    }
    assert {ColRef("encounters", "occurred_at"), ColRef("patients", "email")} <= ins.referenced
    assert ins.annotations == {}
    same = inspect(select(Patient.id, Patient.status.label("status")))
    assert same.renamed == {"status": ColRef("patients", "status")}  # its own name: no shadow
    assert same.columns == {"id": ColRef("patients", "id"), "status": ColRef("patients", "status")}
