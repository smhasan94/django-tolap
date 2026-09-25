"""Realistic SQLAlchemy Select statements for the gap report (SQLAlchemy half)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import aliased

from tests.sqlalchemy.models import Encounter, Patient, encounters, patients

Factory = Callable[[], Any]

SA_CORPUS: list[tuple[str, Factory, str]] = [
    ("entity", lambda: select(Patient), "select(Entity)"),
    ("core_table", lambda: select(patients), "select(table)"),
    ("columns", lambda: select(Patient.id, Patient.region, Patient.status), "explicit columns"),
    (
        "where_ilike",
        lambda: select(Patient).where(Patient.full_name.ilike("%o%")),
        "parameterised ILIKE",
    ),
    (
        "where_or_in",
        lambda: select(Patient).where(
            or_(Patient.region.in_(["us-east", "us-west"]), Patient.status == "deleted")
        ),
        "OR with IN",
    ),
    ("isnot_null", lambda: select(Patient).where(Patient.region.is_not(None)), "IS NOT NULL"),
    (
        "order_limit",
        lambda: select(Patient).order_by(Patient.date_of_birth.desc()).limit(3),
        "ORDER BY + LIMIT",
    ),
    (
        "offset",
        lambda: select(Patient).order_by(Patient.id).limit(3).offset(2),
        "LIMIT with OFFSET",
    ),
    (
        "join",
        lambda: select(Patient).join(Encounter).where(Encounter.status == "active"),
        "inner join",
    ),
    (
        "join_distinct",
        lambda: select(Patient).join(Encounter).where(Encounter.status == "active").distinct(),
        "join + DISTINCT",
    ),
    (
        "outerjoin_count",
        lambda: (
            select(Patient.id, func.count(Encounter.id).label("n"))
            .outerjoin(Encounter)
            .group_by(Patient.id)
        ),
        "aggregate + GROUP BY",
    ),
    (
        "having",
        lambda: (
            select(Patient.id, func.count(Encounter.id).label("n"))
            .join(Encounter)
            .group_by(Patient.id)
            .having(func.count(Encounter.id) > 0)
        ),
        "HAVING",
    ),
    (
        "func_label",
        lambda: select(Patient.id, func.upper(Patient.full_name).label("upper")),
        "function label",
    ),
    (
        "exists",
        lambda: select(Patient).where(exists().where(Encounter.patient_id == Patient.id)),
        "EXISTS",
    ),
    (
        "scalar_subquery",
        lambda: select(
            Patient.id,
            select(Encounter.status)
            .where(Encounter.patient_id == Patient.id)
            .order_by(Encounter.id.desc())
            .limit(1)
            .scalar_subquery()
            .label("last"),
        ),
        "scalar subquery label",
    ),
    (
        "in_subquery",
        lambda: select(Patient).where(
            Patient.id.in_(select(encounters.c.patient_id).where(encounters.c.status == "deleted"))
        ),
        "IN (subquery)",
    ),
    ("aliased", lambda: select(aliased(Patient).id), "aliased entity"),
    (
        "between_dates",
        lambda: select(Patient).where(Patient.date_of_birth.between("1970-01-01", "1989-12-31")),
        "BETWEEN on dates",
    ),
]
