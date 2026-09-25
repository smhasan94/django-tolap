"""compile_filter per operator per dialect; executed rows compared with upstream's post pass."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import Session
from tolap_core import FilterOperator, RowFilter, apply_row_filters

from sqlalchemy_tolap.enforce import dialect_name
from sqlalchemy_tolap.pushdown import DIALECTS, compile_filter
from tests.harness.fixtures import effective_policy
from tests.sqlalchemy.models import encounters, patients
from tests.test_compile_filter import CASES, ROWS, _id


@pytest.fixture
def rows(session: Session) -> Session:
    session.execute(
        insert(patients),
        [
            {
                "id": i,
                "full_name": name,
                "email": f"{i}@x",
                "ssn": "s",
                "date_of_birth": dt.date(2000, 1, i),
                "region": region,
                "status": status,
                "score": score,
            }
            for i, (name, region, score, status) in enumerate(ROWS, start=1)
        ],
    )
    return session


def rf(field: str, operator: str, value=None, values=None) -> RowFilter:  # type: ignore[no-untyped-def]
    return RowFilter(field=field, operator=FilterOperator(operator), value=value, values=values)


def upstream_ids(session: Session, row_filter: RowFilter) -> list[int]:
    rows = [
        dict(r)
        for r in session.execute(
            select(
                patients.c.id,
                patients.c.full_name,
                patients.c.region,
                patients.c.score,
                patients.c.status,
            )
        ).mappings()
    ]
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


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_pushed_filter_selects_exactly_upstream_rows(rows: Session, case: RowFilter) -> None:
    dialect = dialect_name(rows)
    crit = compile_filter(case, patients, dialect)
    if crit is None:
        pytest.skip(f"declined on {dialect}")
    pushed = sorted(rows.execute(select(patients.c.id).where(crit)).scalars())
    assert pushed == upstream_ids(rows, case)


@pytest.mark.parametrize("dialect", sorted(DIALECTS))
def test_dialect_rules(dialect: str) -> None:
    rules = DIALECTS[dialect]
    assert (
        compile_filter(rf("full_name", "like", "a%"), patients, dialect) is not None
    ) == rules.like
    assert (
        compile_filter(rf("region", "equals", "x"), patients, dialect) is not None
    ) == rules.string_equality
    assert (
        compile_filter(rf("region", "greaterThan", "x"), patients, dialect) is not None
    ) == rules.string_order
    assert compile_filter(rf("score", "equals", 1), patients, dialect) is not None
    for op in ("contains", "startsWith", "matches"):
        assert compile_filter(rf("full_name", op, "a"), patients, dialect) is None


def test_unknown_dialect_and_type_mismatches() -> None:
    assert compile_filter(rf("score", "equals", 1), patients, "cockroach") is None
    for case in (
        rf("score", "equals", "10"),
        rf("region", "equals", 5),
        rf("date_of_birth", "equals", "2000-01-01"),
        rf("encounters.status", "equals", "a"),
        rf("nope", "equals", 1),
        rf("full_name", "like", "a" * 1025),
    ):
        assert compile_filter(case, patients, "postgresql") is None, case
    assert (
        compile_filter(rf("patient_id", "equals", 1), encounters, "postgresql") is None
    )  # FK column
    assert compile_filter(rf("date_of_birth", "isNull"), patients, "postgresql") is not None
