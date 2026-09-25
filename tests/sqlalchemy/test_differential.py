"""Upstream fixtures and the Hypothesis property, through the SQLAlchemy adapter."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import delete, exists, func, insert, or_, select
from sqlalchemy.orm import Session

from sqlalchemy_tolap import TolapDenied, enforce
from sqlalchemy_tolap.enforce import dialect_name
from sqlalchemy_tolap.pushdown import prepare_select
from tests.harness.contexts import signed
from tests.harness.fixtures import all_scenarios, operator_corpus
from tests.harness.strategies import patient_rows, policies
from tests.sqlalchemy.conftest import SIGNING_KEY
from tests.sqlalchemy.harness import assert_differential
from tests.sqlalchemy.models import TABLES, Encounter, Patient, encounters, patients, records
from tests.test_differential_fixtures import UNREPRESENTABLE, _assert_mask


@pytest.fixture
def corpus_rows(session: Session) -> Session:
    session.execute(
        insert(records),
        [
            {
                "id": r["id"],
                "score": r.get("score"),
                "region": r.get("region"),
                "name": r.get("name"),
            }
            for r in operator_corpus()[0].records
            if r["id"] not in UNREPRESENTABLE
        ],
    )
    return session


@pytest.mark.parametrize("case", operator_corpus(), ids=lambda c: c.name)
def test_operator_corpus(corpus_rows: Session, case: Any) -> None:
    rows = assert_differential(select(records).order_by(records.c.id), case.policy, corpus_rows)
    expected = [i for i in case.expected_ids if i not in UNREPRESENTABLE]
    assert sorted(r["id"] for r in rows) == sorted(expected), case.notes


@pytest.mark.parametrize(
    ("file_name", "scenario"), all_scenarios(), ids=lambda x: x if isinstance(x, str) else x.name
)
def test_integration_scenario(seeded: Session, file_name: str, scenario: Any) -> None:
    table = TABLES[scenario.table]
    stmt = select(*(table.c[c] for c in scenario.columns)).order_by(table.c.id)
    expected = scenario.expected
    if not expected["pass"]:
        with pytest.raises(TolapDenied) as exc:
            enforce(stmt, signed(scenario.policy), seeded, signing_key=SIGNING_KEY)
        assert expected["errorContains"] in str(exc.value)
        return
    rows = assert_differential(stmt, scenario.policy, seeded)
    assert rows == enforce(stmt, signed(scenario.policy), seeded, signing_key=SIGNING_KEY)
    if "rowCount" in expected:
        assert len(rows) == expected["rowCount"]
    if "idsEqual" in expected:
        assert sorted(r["id"] for r in rows) == sorted(expected["idsEqual"])
    if "regions" in expected:
        assert sorted(r["region"] for r in rows) == sorted(expected["regions"])
    if "maskedField" in expected:
        field, kind = expected["maskedField"]["field"], expected["maskedField"]["mask"]
        for row in rows:
            original = seeded.execute(
                select(table.c[field]).where(table.c.id == row["id"])
            ).scalar_one()
            _assert_mask(kind, original, row[field])
    if "everyRowField" in expected:
        for rule in expected["everyRowField"]:
            assert all(r[rule["field"]] == rule["equals"] for r in rows)


STATEMENTS = [
    lambda: select(Patient),
    lambda: select(Patient).order_by(Patient.id.desc()),
    lambda: select(Patient.id, Patient.region, Patient.status, Patient.score),
    lambda: select(Patient).where(or_(Patient.status == "active", Patient.score >= 50)),
    lambda: select(Patient).where(Patient.region != "eu-west").order_by(Patient.id),
    lambda: select(Patient).order_by(Patient.id).limit(3).offset(1),
    lambda: select(Patient.id, Patient.full_name).order_by(Patient.full_name),
    lambda: (
        select(Patient)
        .join(Encounter)
        .where(Encounter.status == "active")
        .distinct()
        .order_by(Patient.id)
    ),
    lambda: (
        select(Patient.id, func.count(Encounter.id).label("n"))
        .outerjoin(Encounter)
        .group_by(Patient.id)
    ),
    lambda: select(Patient).where(
        exists().where(Encounter.patient_id == Patient.id, Encounter.region == "us-east")
    ),
]


@pytest.mark.usefixtures("session")
class TestProperty:
    @settings(
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    @given(
        rows=patient_rows(),
        policy=policies(),
        which=st.integers(min_value=0, max_value=len(STATEMENTS) - 1),
    )
    def test_pushdown_matches_post_pass(
        self, session: Session, rows: list[dict[str, Any]], policy: Any, which: int
    ) -> None:
        # The session fixture's transaction is rolled back after the test; each example
        # starts by clearing the tables it uses.
        session.execute(delete(encounters))
        session.execute(delete(patients))
        if rows:
            session.execute(insert(patients), rows)
            enc = [
                {
                    "patient_id": r["id"],
                    "occurred_at": dt.datetime(2026, 1, 1),
                    "region": r["region"] or "none",
                    "status": r["status"],
                }
                for r in rows
                if r["id"] % 2
            ]
            if enc:
                session.execute(insert(encounters), enc)
        stmt = STATEMENTS[which]()
        prep = prepare_select(stmt, policy, dialect=dialect_name(session))
        if prep.allowed:
            assert_differential(stmt, policy, session)
        else:
            assert prep.denial_reason
