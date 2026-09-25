from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from django.db import connection
from sqlalchemy import create_engine, insert, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tests.harness.seed import AUDIT, BILLING, ENCOUNTERS, PATIENTS
from tests.sqlalchemy.models import (
    SCHEMA,
    audit_log,
    billing_internal,
    encounters,
    metadata,
    patients,
)

SIGNING_KEY = "test-signing-key"


@pytest.fixture(scope="session")
def sa_engine(django_db_setup, django_db_blocker) -> Iterator[Engine]:  # type: ignore[no-untyped-def]
    """SQLite in memory, a schema in Django's throwaway PostgreSQL test database, or a
    throwaway MySQL database next to it."""
    with django_db_blocker.unblock():
        settings = dict(connection.settings_dict)
        vendor = connection.vendor
    drivers = {"postgresql": "postgresql+psycopg", "mysql": "mysql+mysqldb"}
    if vendor in drivers:
        url = URL.create(
            drivers[vendor],
            username=settings.get("USER") or None,
            password=settings.get("PASSWORD") or None,
            host=settings.get("HOST") or None,
            port=int(settings["PORT"]) if settings.get("PORT") else None,
            database=settings["NAME"],
        )
        engine = create_engine(url)
        with engine.begin() as conn:
            if vendor == "postgresql":
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
            else:
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {SCHEMA} CHARACTER SET utf8mb4"))
    else:
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    metadata.create_all(engine)
    yield engine
    metadata.drop_all(engine)
    if vendor == "mysql":
        with engine.begin() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {SCHEMA}"))
    engine.dispose()


@pytest.fixture
def session(sa_engine: Engine) -> Iterator[Session]:
    """A Session on one connection inside a transaction that is rolled back afterwards."""
    with sa_engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as sess:
            yield sess
        trans.rollback()


@pytest.fixture
def seeded(session: Session) -> Session:
    session.execute(
        insert(patients),
        [
            {
                "id": i,
                "full_name": n,
                "email": e,
                "ssn": s,
                "date_of_birth": dt.date.fromisoformat(d),
                "region": r,
                "status": st,
            }
            for i, (n, e, s, d, r, st) in enumerate(PATIENTS, start=1)
        ],
    )
    session.execute(
        insert(encounters),
        [
            {
                "id": i,
                "patient_id": p,
                "occurred_at": dt.datetime.fromisoformat(o),
                "region": r,
                "status": st,
            }
            for i, (p, o, r, st) in enumerate(ENCOUNTERS, start=1)
        ],
    )
    session.execute(
        insert(billing_internal),
        [
            {"id": i, "patient_id": p, "amount_cents": a, "region": r}
            for i, (p, a, r) in enumerate(BILLING, start=1)
        ],
    )
    session.execute(
        insert(audit_log),
        [
            {"id": i, "actor": a, "action": ac, "occurred_at": dt.datetime.fromisoformat(o)}
            for i, (a, ac, o) in enumerate(AUDIT, start=1)
        ],
    )
    session.flush()
    return session
